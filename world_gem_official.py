"""Independent ECCC GDPS full-globe field reader (no Open-Meteo mixing).

Source specification:
https://eccc-msc.github.io/open-data/msc-data/nwp_gdps/readme_gdps-datamart_en/
GRIB2 metadata, not filename or data median, decides time/grid/units.
No live publishing, no arbitrary URL, no credential.
"""
from datetime import timedelta
import math
import numpy as np

ROOT='https://dd.weather.gc.ca'
MAX_FILE=16*1024*1024
NX,NY=2400,1201
# Exact documented nomenclature; an unavailable or unrecognized field stays absent.
FIELDS={
    'temperature_2m':('AirTemp_AGL-2m','heightAboveGround',2,('2t','t'), 'temperature'),
    'relative_humidity_2m':('RelativeHumidity_AGL-2m','heightAboveGround',2,('2r','r'), 'rh'),
    'surface_pressure':('Pressure_Sfc','surface',0,('sp','pres'), 'pressure'),
    'pressure_msl':('Pressure_MSL','meanSea',0,('msl','prmsl','pres'), 'pressure'),
    'wind_u_component_10m':('WindU_AGL-10m','heightAboveGround',10,('10u','u'), 'wind'),
    'wind_v_component_10m':('WindV_AGL-10m','heightAboveGround',10,('10v','v'), 'wind'),
}
for _p in (925,850,700,500):
    for _key,_name,_short,_kind in (
        ('temperature','AirTemp',('t',),'temperature'),
        ('relative_humidity','RelativeHumidity',('r',),'rh'),
        ('geopotential_height','GeopotentialHeight',('gh','hgt'),'height'),
        ('wind_u_component','WindU',('u',),'wind'),
        ('wind_v_component','WindV',('v',),'wind')):
        FIELDS[f'{_key}_{_p}hPa']=(f'{_name}_IsbL-{_p:04d}','isobaricInhPa',_p,_short,_kind)
DEFAULT_FIELDS=tuple(['surface_pressure','pressure_msl','temperature_2m','relative_humidity_2m',
                      'geopotential_height_500hPa']+
                     [f'{v}_{p}hPa' for p in (925,850,700,500)
                      for v in ('temperature','relative_humidity')]+
                     [f'wind_{c}_component_{p}hPa' for p in (850,500) for c in ('u','v')])

def lead_hours(run,valid):
    if run.utcoffset()!=timedelta(0) or valid.utcoffset()!=timedelta(0):
        raise ValueError('UTC required')
    h=(valid-run).total_seconds()/3600
    if run.hour not in (0,12) or run.minute or run.second or run.microsecond or h!=int(h) or not 0<=h<=240:
        raise ValueError('invalid GDPS cycle or lead')
    if h>84 and h%3:raise ValueError('unpublished GDPS lead')
    return int(h)

def field_url(run,valid,key):
    h=lead_hours(run,valid);name=FIELDS[key][0]
    return f'{ROOT}/{run:%Y%m%d}/WXO-DD/model_gdps/15km/{run:%H}/{h:03d}/{run:%Y%m%dT%H}Z_MSC_GDPS_{name}_LatLon0.15_PT{h:03d}H.grib2'

def convert(a,kind,unit):
    unit=unit.strip()
    if kind=='temperature' and unit=='K':return a-273.15
    if kind=='pressure' and unit=='Pa':return a/100.
    if kind=='pressure' and unit=='hPa':return a
    if kind=='rh' and unit=='%':return a
    if kind=='height' and unit in ('gpm','m'):return a
    if kind=='wind' and unit in ('m s**-1','m s-1','m/s'):return a
    raise ValueError('unrecognized physical unit')

def decode(raw,key,run,valid):
    import eccodes as ec
    if not isinstance(raw,bytes) or not 20<=len(raw)<=MAX_FILE or raw[:4]!=b'GRIB' or raw[-4:]!=b'7777':
        raise ValueError('invalid GRIB2 bytes')
    if raw[7]!=2 or int.from_bytes(raw[8:16],'big')!=len(raw):
        raise ValueError('not one complete GRIB2 message')
    _,typ,level,shorts,kind=FIELDS[key]
    lead_hours(run,valid)
    g=ec.codes_new_from_message(raw)
    try:
        get=lambda k:ec.codes_get(g,k)
        if (int(get('dataDate'))!=int(run.strftime('%Y%m%d')) or int(get('dataTime'))!=int(run.strftime('%H%M'))
            or int(get('validityDate'))!=int(valid.strftime('%Y%m%d')) or int(get('validityTime'))!=int(valid.strftime('%H%M'))):
            raise ValueError('wrong GRIB reference/valid time')
        if get('stepType')!='instant' or get('typeOfLevel')!=typ or int(get('level'))!=level or get('shortName') not in shorts:
            raise ValueError('wrong GRIB variable or level')
        if (get('gridType')!='regular_ll' or int(get('Ni'))!=NX or int(get('Nj'))!=NY
            or int(get('iScansNegatively')) or int(get('jPointsAreConsecutive')) or int(get('alternativeRowScanning'))):
            raise ValueError('unsupported grid scanning')
        lat1,lat2,lon1,lon2,dx,dy=map(float,[get(k) for k in (
            'latitudeOfFirstGridPointInDegrees','latitudeOfLastGridPointInDegrees',
            'longitudeOfFirstGridPointInDegrees','longitudeOfLastGridPointInDegrees',
            'iDirectionIncrementInDegrees','jDirectionIncrementInDegrees')])
        if not all(math.isfinite(x) for x in (lat1,lat2,lon1,lon2,dx,dy)):
            raise ValueError('invalid geographic coordinates')
        if (abs(dx-.15)>1e-6 or abs(dy-.15)>1e-6 or abs(lon1)>1e-6 or abs(lon2-359.85)>1e-5
            or sorted((lat1,lat2))!=[-90.,90.] or bool(get('jScansPositively'))!=(lat2>lat1)):
            raise ValueError('wrong global grid origin or coverage')
        if kind=='wind' and int(get('uvRelativeToGrid')) not in (0,1):
            raise ValueError('unknown wind orientation')
        a=np.asarray(ec.codes_get_values(g),np.float32).reshape(NY,NX)
        if int(get('bitmapPresent')):
            a=np.where(a==float(get('missingValue')),np.nan,a)
        unit=str(get('units'))
        a=convert(a,kind,unit)
        if lat1>lat2:a=a[::-1]
        # The source begins at Greenwich; shift to -180..179.85 exactly.
        a=np.roll(a,NX//2,axis=1).astype(np.float32,copy=False)
        if not np.isfinite(a).any():raise ValueError('all missing')
        return a,{'short_name':str(get('shortName')),'source_unit':unit,'level':level,
                  'grid':[NX,NY],'origin':[-180,-90],'spacing':[.15,.15]}
    finally:ec.codes_release(g)

def read(run,valid,keys=DEFAULT_FIELDS,session=None):
    """Read only fixed public ECCC variables; independently record failures."""
    import requests
    keys=tuple(dict.fromkeys(keys))
    if len(keys)>len(DEFAULT_FIELDS) or any(k not in FIELDS for k in keys):
        raise ValueError('unsupported request')
    own=session is None
    session=requests.Session() if own else session
    fields={};report={}
    try:
        for key in keys:
            url=field_url(run,valid,key)
            try:
                with session.get(url,timeout=(8,40),stream=True,allow_redirects=False) as response:
                    if response.status_code!=200:
                        report[key]={'status':'http_'+str(response.status_code)}
                        continue
                    data=bytearray()
                    for chunk in response.iter_content(65536):
                        if len(data)+len(chunk)>MAX_FILE:raise ValueError('file size limit')
                        data.extend(chunk)
                a,meta=decode(bytes(data),key,run,valid)
                fields[key]=a
                report[key]={'status':'verified','source_url':url,**meta,
                             'finite_fraction':round(float(np.isfinite(a).mean()),5)}
            except (requests.RequestException,ValueError,RuntimeError,KeyError) as e:
                report[key]={'status':'rejected','reason':type(e).__name__+': '+str(e)[:120]}
    finally:
        if own:session.close()
    return fields,report

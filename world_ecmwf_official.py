"""Bounded official ECMWF Open Data GRIB message reader for IFS and AIFS.

Implements documented per-field .index/HTTP Range pattern. No whole-file
download, arbitrary endpoints, host publication, or intermediary mixing.
"""
from datetime import timedelta
import json,re
import numpy as np

ROOT='https://data.ecmwf.int/forecasts'
MAX_INDEX=2*1024*1024
MAX_MESSAGE=32*1024*1024
FIELDS={'t2m':('2t','heightAboveGround',2,'instant'),
        'z500':('z','isobaricInhPa',500,'instant'),
        'pacc':('tp','surface',0,'accum'),
        'orog':('z','surface',0,'instant')}
def urls(model,res,run,lead,key):
    if model not in ('ifs','aifs-single') or res not in ('0p1','0p25') or (model=='aifs-single' and res!='0p25'):
        raise ValueError('unsupported official model/grid')
    if run.utcoffset()!=timedelta(0) or run.hour not in (0,6,12,18) or run.minute or run.second or run.microsecond:
        raise ValueError('invalid UTC initialization')
    if type(lead) is not int or lead<0 or lead>360 or lead%6 or key not in FIELDS:raise ValueError('invalid forecast request')
    suffix=('-pl' if key=='z500' else '-sfc') if res=='0p1' else ''
    base=f'{ROOT}/{run:%Y%m%d}/{run:%H}z/{model}/{res}/oper/{run:%Y%m%d%H}0000-{lead}h-oper-fc{suffix}'
    return base+'.index',base+'.grib2'

def select(index,key,lead):
    if len(index)>MAX_INDEX:raise ValueError('oversize index')
    param,_,level,_=FIELDS[key];matches=[]
    for line in index.splitlines():
        row=json.loads(line)
        if not isinstance(row,dict) or row.get('param')!=param:continue
        if key=='z500' and str(row.get('levelist'))!='500':continue
        if key=='orog' and (row.get('levtype')!='sfc' or row.get('levelist') not in (None,'',0,'0')):continue
        if str(row.get('step'))!=str(lead):continue
        start,length=row.get('_offset'),row.get('_length')
        if type(start) is not int or type(length) is not int or not 0<=start<=2**40 or not 20<=length<=MAX_MESSAGE:
            raise ValueError('unsafe indexed range')
        matches.append((start,length))
    if len(matches)!=1:raise ValueError('missing or ambiguous indexed field')
    return matches[0]

def fetch(session,url,limit,headers=None):
    with session.get(url,headers=headers or {},stream=True,allow_redirects=False,timeout=(10,40)) as r:
        if headers:
            if r.status_code!=206:raise ValueError('range response not partial')
            m=re.fullmatch(r'bytes (\d+)-(\d+)/(\d+|\*)',r.headers.get('Content-Range',''))
            requested=headers['Range'].removeprefix('bytes=')
            if not m or f'{m[1]}-{m[2]}'!=requested:raise ValueError('wrong range response')
        elif r.status_code!=200:raise ValueError('official HTTP '+str(r.status_code))
        data=bytearray()
        for chunk in r.iter_content(65536):
            if len(data)+len(chunk)>limit:raise ValueError('response exceeds byte cap')
            data.extend(chunk)
        return bytes(data)

def decode(data,run,lead,key,res):
    import eccodes as ec
    if len(data)<20 or data[:4]!=b'GRIB' or data[7]!=2 or data[-4:]!=b'7777' or int.from_bytes(data[8:16],'big')!=len(data):
        raise ValueError('not one complete GRIB2 message')
    g=ec.codes_new_from_message(data)
    try:
        get=lambda k:ec.codes_get(g,k)
        param,typ,level,step=FIELDS[key];valid=run+timedelta(hours=lead)
        if int(get('dataDate'))!=int(run.strftime('%Y%m%d')) or int(get('dataTime'))!=int(run.strftime('%H%M')) or int(get('validityDate'))!=int(valid.strftime('%Y%m%d')) or int(get('validityTime'))!=int(valid.strftime('%H%M')):
            raise ValueError('reference or valid time mismatch')
        if get('shortName')!=param or get('typeOfLevel')!=typ or int(get('level'))!=level or get('stepType')!=step:
            raise ValueError('wrong variable, level or step type')
        if key=='pacc' and (int(get('startStep'))!=0 or int(get('endStep'))!=lead):
            raise ValueError('not accumulation from initialization')
        if get('gridType')!='regular_ll' or get('iScansNegatively') or get('jPointsAreConsecutive') or get('alternativeRowScanning'):
            raise ValueError('unsupported grid')
        d=.1 if res=='0p1' else .25
        nx,ny=int(get('Ni')),int(get('Nj'))
        if (nx,ny)!=(round(360/d),round(180/d)+1):raise ValueError('wrong global shape')
        lon1,lon2,lat1,lat2,dx,dy=[float(get(k)) for k in ('longitudeOfFirstGridPointInDegrees','longitudeOfLastGridPointInDegrees','latitudeOfFirstGridPointInDegrees','latitudeOfLastGridPointInDegrees','iDirectionIncrementInDegrees','jDirectionIncrementInDegrees')]
        if sorted((lat1,lat2))!=[-90.,90.] or abs(dx-d)>1e-6 or abs(dy-d)>1e-6 or abs((lon2-lon1)%360-(360-d))>1e-5:
            raise ValueError('wrong coordinates')
        if abs(lon1)>1e-6 and abs(lon1+180)>1e-6 and abs(lon1-180)>1e-6:raise ValueError('unknown longitude origin')
        a=np.asarray(ec.codes_get_values(g),dtype=np.float32).reshape(ny,nx)
        if not get('jScansPositively'):a=a[::-1]
        if abs(lon1)<1e-6:a=np.roll(a,nx//2,axis=1)
        unit=str(get('units'))
        if key=='t2m' and unit=='K':a=a-273.15;out='°C';lo,hi=-110,65
        elif key=='z500' and unit in ('m**2 s**-2','m2 s-2'):a=a/9.80665;out='m';lo,hi=3500,7000
        elif key=='orog' and unit in ('m**2 s**-2','m2 s-2'):a=a/9.80665;out='m';lo,hi=-500,9000
        elif key=='pacc' and unit=='m':a=a*1000;out='mm';lo,hi=-.001,5000
        elif key=='pacc' and unit in ('kg m**-2','kg m-2'):out='mm';lo,hi=-.001,5000
        else:raise ValueError('unknown unit')
        good=np.isfinite(a)&(a>=lo)&(a<=hi)
        if float(good.mean())<.99:raise ValueError('insufficient physical coverage')
        a=np.where(good,a,np.nan)
        return a,dict(grid=[nx,ny],origin=[-180,-90],spacing=[d,d],units=out,source_unit=unit,
                       finite_fraction=round(float(good.mean()),5),min=float(np.nanmin(a)),max=float(np.nanmax(a)),lead_hours=lead,
                       accumulation_start_hour=0 if key=='pacc' else None)
    finally:ec.codes_release(g)

def read(session,model,res,run,lead,key):
    idx,url=urls(model,res,run,lead,key)
    start,n=select(fetch(session,idx,MAX_INDEX),key,lead)
    data=fetch(session,url,n,{'Range':f'bytes={start}-{start+n-1}','Accept-Encoding':'identity'})
    if len(data)!=n:raise ValueError('short range')
    a,meta=decode(data,run,lead,key,res)
    return a,dict(**meta,source_url=url,index_url=idx,range_offset=start,range_bytes=n,
                  producer='ECMWF',distribution='producer',source_licence='CC BY 4.0; ECMWF attribution')

def daily_precip(later,earlier):
    if later.shape!=earlier.shape:raise ValueError('incompatible grid')
    d=later-earlier
    if np.any(d[np.isfinite(d)]<-.02):raise ValueError('accumulation reset or inconsistent source')
    return np.maximum(d,0)

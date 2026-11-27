"""Build an explicitly identified NOAA PSL synoptic Z500 normal.

Read a single pressure-level slice, not the full ~1GB upstream file.
No automatic replacement of ERA5, no forecast publication.
"""
import argparse,hashlib,json,os
from datetime import datetime,timedelta
from pathlib import Path
import numpy as np
from pressure_anomaly import SynopticReference

URL='https://psl.noaa.gov/thredds/dodsC/Datasets/ncep.reanalysis.derived/pressure/hgt.4Xday.ltm.1991-2020.nc'
SOURCE='NCEP-NCAR Reanalysis 1'
HOURS=[0,6,12,18]
TIME_COUNT=1460
def verify_axes(lat,lon,level,time):
    if not np.array_equal(lat,np.arange(90,-90.1,-2.5)) or not np.array_equal(lon,np.arange(0,360,2.5)):
        raise ValueError('unexpected NOAA grid')
    if level.shape!=(17,) or np.count_nonzero(level==500)!=1:
        raise ValueError('missing or ambiguous 500 hPa')
    if time.shape!=(TIME_COUNT,) or not np.isfinite(time).all() or not np.array_equal(np.diff(time),np.full(TIME_COUNT-1,6.)):
        raise ValueError('unexpected 365-day synoptic time coordinate')
    return int(np.flatnonzero(level==500)[0])

def build(path):
    from netCDF4 import Dataset,num2date
    path=Path(path)
    # Read bounded metadata and coordinates first, then request exactly one level.
    with Dataset(URL+'?lat,lon,level,time') as ds:
        if getattr(ds,'dataset_title','')!=SOURCE:
            raise ValueError('wrong climate source')
        t=ds.variables['time']
        if getattr(t,'climo_period','')!='1991/01/01 00Z - 2020/12/31 18Z':
            raise ValueError('wrong climatology period')
        if getattr(t,'units','')!='hours since 1800-01-01 00:00:0.0':
            raise ValueError('unknown climate time units')
        lat,lon,level,time=[np.asarray(ds.variables[k][:]) for k in ('lat','lon','level','time')]
        lev=verify_axes(lat,lon,level,time)
        # NOAA's climatology coordinate encodes a non-leap synthetic year.
        dates=num2date(time,t.units,calendar=getattr(t,'calendar','standard'))
        expected=[datetime(2001,1,1)+timedelta(hours=6*i) for i in range(TIME_COUNT)]
        if [(d.month,d.day,d.hour) for d in dates]!=[(d.month,d.day,d.hour) for d in expected]:
            raise ValueError('calendar does not align to month/day and UTC hour')
    # A DAP2 projection restricts the server to 500 hPa on the 2.5-degree
    # native climate grid, including actual annual sample counts.
    sl=f'[0:1:1459][{lev}:1:{lev}][0:1:72][0:1:143]'
    with Dataset(URL+'?hgt'+sl+',valid_yr_count'+sl) as ds:
        h=ds.variables['hgt'];n=ds.variables['valid_yr_count']
        if getattr(h,'units','')!='m' or getattr(h,'statistic','')!='Long Term Mean':
            raise ValueError('wrong normal units/statistic')
        if h.shape!=(TIME_COUNT,1,73,144) or n.shape!=h.shape:
            raise ValueError('subset not exactly one level')
        field=np.asarray(np.ma.filled(np.ma.asarray(h[:],dtype=np.float32),np.nan))[:,0]
        counts=np.asarray(np.ma.filled(np.ma.asarray(n[:]),0))[:,0]
        if not np.isfinite(field).all() or np.min(field)<3500 or np.max(field)>7000:
            raise ValueError('height normal physical coverage invalid')
        if np.min(counts)<29 or np.max(counts)>30:
            raise ValueError('insufficient contributing years')
    # Descending latitude -> ascending; longitude native 0..357.5 periodic.
    values=field[:,::-1,:].reshape(365,4,73,144)
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix('.tmp.npz');np.savez_compressed(tmp,lat=lat[::-1],lon=lon,field=values)
    meta=dict(schema=1,source=SOURCE,parameter='z500',units='m',base_period='1991-2020',
              temporal_basis='synoptic_6h',calendar='365_month_day',hours_utc=HOURS,
              source_url=URL,source_level_hpa=500,grid_spacing_degrees=2.5,
              attribution='NCEP-NCAR Reanalysis 1 data provided by NOAA PSL, Boulder, Colorado, USA',
              min_contributing_years=int(np.min(counts)),max_contributing_years=int(np.max(counts)),
              sha256=hashlib.sha256(tmp.read_bytes()).hexdigest())
    mp=Path(str(path)+'.json');mt=Path(str(mp)+'.tmp');mt.write_text(json.dumps(meta,indent=2))
    SynopticReference.load(tmp,mt,'z500',SOURCE)
    os.replace(tmp,path);os.replace(mt,mp)
    return {**meta,'shape':list(values.shape),'bytes':path.stat().st_size,'min':float(values.min()),'max':float(values.max())}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    print(json.dumps(build(a.out)),flush=True)

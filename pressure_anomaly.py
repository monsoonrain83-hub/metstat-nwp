"""Six-hour pressure anomalies from the actual same-run forecast frame.

No daily aggregation. References must explicitly name the source, normal
period, calendar, synoptic hours, physical units and exact file checksum.
ERA5 1991–2020 is preferred. The NOAA NCEP/NCAR 1991–2020 four-times-daily
reference is an explicit alternative, not a silent fallback.
"""
from datetime import datetime, timedelta
from pathlib import Path
import hashlib
import json
import zipfile
import numpy as np
from scipy.ndimage import map_coordinates

HOURS = (0, 6, 12, 18)
LIMITS = {'z850':(-500,2500),'z700':(1500,4500),'z500':(3500,7000),
          'z300':(6500,11500),'mslp':(800,1150)}
MAX_ARCHIVE=100*1024*1024
MAX_EXPANDED=160*1024*1024

def aligned(run, valid):
    if run.utcoffset()!=timedelta(0) or valid.utcoffset()!=timedelta(0):
        return False
    return (run.hour in HOURS and valid.hour in HOURS
            and not any((run.minute,run.second,run.microsecond,valid.minute,valid.second,valid.microsecond))
            and valid>=run and (valid-run).total_seconds()%21600==0)

def physical(value, parameter):
    if not isinstance(value,np.ndarray) or value.ndim!=2 or not value.size:
        return None
    a=np.asarray(np.ma.filled(np.ma.asarray(value,dtype=np.float32),np.nan))
    lo,hi=LIMITS[parameter]
    good=np.isfinite(a)&(a>=lo)&(a<=hi)
    return np.where(good,a,np.nan) if good.any() else None

def axis(value, lo, hi):
    a=np.asarray(value,dtype=np.float64)
    if a.ndim!=1 or len(a)<2 or not np.isfinite(a).all():
        raise ValueError('invalid climate coordinate')
    d=np.diff(a)
    if not (d>0).all() or not np.allclose(d,d[0],atol=1e-6,rtol=0):
        raise ValueError('nonregular climate coordinate')
    if a[0]<lo or a[-1]>hi: raise ValueError('coordinate outside bounds')
    return a

class SynopticReference:
    """One parameter per file; 365/366 calendar days and exactly 4 UTC hours."""
    def __init__(self,arrays,metadata,parameter,source='ERA5'):
        calendar=metadata.get('calendar')
        if (source not in ('ERA5','NCEP-NCAR Reanalysis 1') or
            metadata.get('source')!=source or metadata.get('schema')!=1 or
            metadata.get('parameter')!=parameter or parameter not in LIMITS or
            metadata.get('base_period')!='1991-2020' or metadata.get('temporal_basis')!='synoptic_6h' or
            metadata.get('hours_utc')!=list(HOURS) or
            metadata.get('units')!=('hPa' if parameter=='mslp' else 'm') or
            calendar not in ('365_month_day','366_month_day')):
            raise ValueError('reference contract mismatch')
        if source=='ERA5' and calendar!='366_month_day':
            raise ValueError('ERA5 requires explicit leap-day climatology')
        self.parameter=parameter
        self.source=source
        self.calendar=calendar
        self.lat=axis(arrays['lat'],-90,90)
        self.lon=axis(arrays['lon'],-180,360)
        self.values=arrays['field']
        shape=(366 if calendar.startswith('366') else 365,4,len(self.lat),len(self.lon))
        if self.values.shape!=shape or self.values.dtype.kind!='f':
            raise ValueError('reference array dimensions/type')
        lo,hi=LIMITS[parameter]
        if not np.isfinite(self.values).all() or self.values.min()<lo or self.values.max()>hi:
            raise ValueError('reference height/pressure unit or coverage mismatch')
        self.values=self.values.astype(np.float32,copy=False)

    @classmethod
    def load(cls,path,metadata_path,parameter,source='ERA5'):
        path,metadata_path=Path(path),Path(metadata_path)
        if path.stat().st_size>MAX_ARCHIVE or metadata_path.stat().st_size>8192:
            raise ValueError('reference cache too large')
        metadata=json.loads(metadata_path.read_text(encoding='utf8'))
        digest=hashlib.sha256()
        with path.open('rb') as f:
            for b in iter(lambda:f.read(1024*1024),b''):digest.update(b)
            if metadata.get('sha256')!=digest.hexdigest():raise ValueError('reference checksum')
            f.seek(0)
            with zipfile.ZipFile(f) as z:
                if sorted(z.namelist())!=['field.npy','lat.npy','lon.npy'] or sum(i.file_size for i in z.infolist())>MAX_EXPANDED:
                    raise ValueError('invalid reference archive')
            f.seek(0)
            with np.load(f,allow_pickle=False) as a:
                return cls(a,metadata,parameter,source)

    def at(self,valid,region):
        if valid.utcoffset()!=timedelta(0) or valid.hour not in HOURS or any((valid.minute,valid.second,valid.microsecond)):
            return None
        i=HOURS.index(valid.hour)
        if self.calendar=='365_month_day' and (valid.month,valid.day)==(2,29):
            # NOAA normals omit Feb 29. Only interpolate same UTC hour.
            f=(self.values[58,i]+self.values[59,i])*.5
        else:
            year=2000 if self.calendar=='366_month_day' else 2001
            day=datetime(year,valid.month,valid.day).timetuple().tm_yday-1
            f=self.values[day,i]
        lat,lon=np.asarray(region.lat),np.asarray(region.lon)
        if lat.shape!=lon.shape or lat.ndim!=2 or not lat.size or not np.isfinite(lat).all() or not np.isfinite(lon).all():
            return None
        # Periodic longitude only for a verified complete 360-degree grid.
        dx=self.lon[1]-self.lon[0]
        periodic=np.isclose(self.lon[-1]-self.lon[0]+dx,360,atol=1e-5)
        if periodic:
            lon=(lon-self.lon[0])%360+self.lon[0]
            f=np.concatenate((f,f[:,:1]),axis=1)
            xmax=self.lon[0]+360
        else:
            xmax=self.lon[-1]
        if lat.min()<self.lat[0] or lat.max()>self.lat[-1] or lon.min()<self.lon[0] or lon.max()>xmax:
            return None
        coords=np.array([(lat-self.lat[0])/(self.lat[1]-self.lat[0]),(lon-self.lon[0])/dx])
        return map_coordinates(f,coords,order=1,mode='constant',cval=np.nan,prefilter=False)

def anomaly(source,raw,parameter,valid,region,reference):
    if reference is None:return None
    f=physical(raw,parameter)
    if f is None:return None
    if parameter in ('z850','z700'):
        try:hs=source.hsurf()
        except Exception:return None
        if not isinstance(hs,np.ndarray) or hs.shape!=f.shape:return None
        f=np.where(np.isfinite(hs)&(hs<f),f,np.nan)
    z=region.interp(source,f)
    coverage=region.interp(source,np.isfinite(f).astype(np.float32))
    c=reference.at(valid,region)
    if c is None or z is None or coverage is None or z.shape!=c.shape or coverage.shape!=c.shape:return None
    good=np.isfinite(z)&np.isfinite(c)&(coverage>=1-1e-6)
    if not good.any():return None
    factor=1.0 if parameter=='mslp' else 10.0
    return np.where(good,(z-c)/factor,np.nan).astype(np.float32),np.where(good,z/factor,np.nan).astype(np.float32)

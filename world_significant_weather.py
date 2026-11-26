"""World simulated weather from a documented backward precipitation interval.

Open-Meteo open-data README, Data Organization/Updates:
https://github.com/open-meteo/open-data#updates-to-real-time-weather-forecasts
data_spatial uses native timesteps and backward sums omit initial time.
Only the completed latest.json of the exact domain/run can define the
interval here. A partial run or unsupported cadence does not certify it.
Raw model precipitation rate is used for this *staging* diagnostic,
as in the existing regional SigWx/reflectivity kernels; it is not a
DEM-corrected precipitation forecast product.
"""
from datetime import datetime,timedelta,timezone
import numpy as np
import nwp_maps as N

PRODUCTS={'refl':('dBZ','refl'),'sigwx':('','sigwx')}
INPUTS={'precipitation','snowfall_water_equivalent','precipitation_type',
        'temperature_2m','relative_humidity_2m','cape',
        'wind_u_component_10m','wind_v_component_10m','wind_speed_10m'}
DOMAINS=frozenset(('ecmwf_ifs','ecmwf_ifs025','ncep_gfs013','ncep_gfs025',
                   'dwd_icon','ukmo_global_deterministic_10km','cmc_gem_gdps_15km'))

def completed_interval(source,run,valid,parse_time):
    """Return exact interval for published completed native run; otherwise None."""
    if source.dom not in DOMAINS or valid<=run:return None
    try:
        meta=source.jget('latest.json')
        if not isinstance(meta,dict) or parse_time(meta['reference_time'])!=run:return None
        if meta.get('completed') is False:return None
        raw=meta['valid_times']
        if not isinstance(raw,list) or len(raw)>500:return None
        times=sorted(set(parse_time(x) for x in raw))
        if not times or times[0]!=run or valid not in times:return None
        i=times.index(valid)
        if i==0:return None
        # Native cadence may change. Reject unsupported or broken intervals;
        # latest.json documents all published native steps of a complete run.
        if any((b-a).total_seconds() not in (3600,10800,21600) for a,b in zip(times[:i],times[1:i+1])):
            return None
        start=times[i-1]
        if not source.exists(run,start):return None
        return start,valid
    except (ValueError,KeyError,TypeError,AttributeError,IndexError,OSError):
        return None

def derive(source,data,validate_grid,interval,requested):
    if source.dom not in DOMAINS or not interval:return {}
    start,end=interval
    if (start.utcoffset()!=timedelta(0) or end.utcoffset()!=timedelta(0)
        or (end-start).total_seconds() not in (3600,10800,21600)):return {}
    hours=(end-start).total_seconds()/3600
    def get(k,lo,hi):
        v=data.get(k)
        if v is None:return None
        try:v=validate_grid(source,v)
        except (ValueError,TypeError,AttributeError):return None
        a=np.asarray(np.ma.filled(np.ma.asarray(v,dtype=np.float32),np.nan))
        return np.where(np.isfinite(a)&(a>=lo)&(a<=hi),a,np.nan)
    p=get('precipitation',0,2000)
    if p is None:return {}
    rate=p/hours
    t=get('temperature_2m',-100,65);snow=get('snowfall_water_equivalent',0,2000)
    if snow is not None:
        valid_snow=np.isfinite(snow)&(snow<=p+.05)
        sf=np.where(valid_snow,np.clip(snow/np.maximum(p,1e-3),0,1),np.nan)
        phase='native snowfall water equivalent'
        phase_keys=['snowfall_water_equivalent']
    elif t is not None:
        sf=N.snow_frac_t(t);phase='existing temperature-based snow fraction approximation'
        phase_keys=['temperature_2m']
    else:return {}
    out={}
    common=dict(interval_start_utc=start.strftime('%Y-%m-%dT%H:%M:%SZ'),
                interval_end_utc=end.strftime('%Y-%m-%dT%H:%M:%SZ'),
                interval_hours=hours,precipitation_basis='native backward sum; raw model rate; not DEM corrected',
                phase_basis=phase,clear_value=-1)
    valid=np.isfinite(rate)&np.isfinite(sf)
    if 'refl' in requested:
        f=N.refl_from_rate(rate,sf)
        # Distinguish no echo from missing inputs in the world raster.
        f=np.where(valid,np.where(rate>=.05,f,-1),np.nan).astype(np.float32)
        if np.isfinite(f).any():out['refl']=(f,dict(common,input_variables=['precipitation']+phase_keys,
            calculation='existing simulated reflectivity from rain/snow rate (not radar observation)'))
    if 'sigwx' in requested:
        rh=get('relative_humidity_2m',0,100);cape=get('cape',0,15000)
        u=get('wind_u_component_10m',-200,200);v=get('wind_v_component_10m',-200,200)
        wind=np.hypot(u,v) if u is not None and v is not None else get('wind_speed_10m',0,200)
        wind_keys=['wind_u_component_10m','wind_v_component_10m'] if u is not None and v is not None else ['wind_speed_10m']
        pt=get('precipitation_type',0,15)
        # Require CAPE and wind for the full existing thunderstorm/fog classification.
        if all(x is not None for x in (t,rh,cape,wind)):
            mask=valid&np.isfinite(t)&np.isfinite(rh)&np.isfinite(cape)&np.isfinite(wind)
            if pt is not None:mask&=np.isfinite(pt)
            f=N.sig_weather(rate,sf,t,rh,cape,pt,wind)
            f=np.where(mask,np.where(np.isfinite(f),f,-1),np.nan).astype(np.float32)
            if np.isfinite(f).any():out['sigwx']=(f,dict(common,
                input_variables=sorted(set(['precipitation','temperature_2m','relative_humidity_2m','cape']+phase_keys+wind_keys+(['precipitation_type'] if pt is not None else []))),
                calculation='existing MetStat diagnostic significant weather; not official warnings',
                ice_type_available=pt is not None))
    return out

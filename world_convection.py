"""Opt-in global convection staging for the five core model families.

Reuse current MetStat thermodynamic kernels and palettes. All dependencies
come from one verified source, one native grid and one forecast frame.
Never infer precipitation interval semantics or replace missing fields
with zero. This initial tranche does not publish hazards or SigWx.
"""
import numpy as np
import nwp_maps as N
import secondary as S

MODELS=frozenset(('ecmwf','gfs','icon','ukmo','gem'))
PRODUCTS={
    'cape':('J/kg','cape'), 'cin':('J/kg','cin'), 'li':('K','li'),
    'ki':('K','ki'), 'si':('K','si'), 'tt':('K','tt'),
    'gdi':('','gdi'), 'shw':('K','shw'),
    'lr75':('K/km','lr'), 'lr85':('K/km','lr'),
    'sh85':('m/s','shr'), 'sh06':('m/s','shr'),
    'ko':('K','ko'), 'swt':('','swt'),
}
LEVELS=(925,850,700,500)
INPUTS={'cape','convective_inhibition','lifted_index','surface_pressure',
        'pressure_msl','temperature_2m','relative_humidity_2m',
        'wind_u_component_10m','wind_v_component_10m'}
INPUTS|={f'{v}_{p}hPa' for p in LEVELS for v in
         ('temperature','relative_humidity','wind_u_component','wind_v_component')}

def derive(model,source,data,validate_grid,selected=None):
    if model not in MODELS:raise ValueError('convection not enabled for model')
    requested=set(PRODUCTS if selected is None else selected)
    if not requested<=PRODUCTS.keys():raise ValueError('unsupported convection product')
    out={}
    # Source adapter contract: Open-Meteo temperatures °C, pressure hPa,
    # RH percent, wind m/s, CAPE/CIN J/kg. Reject out-of-range values; no
    # heuristic per-frame Kelvin or pressure conversion.
    def get(key,lo,hi):
        a=data.get(key)
        if a is None:return None
        try:a=validate_grid(source,a)
        except (ValueError,TypeError,AttributeError):return None
        a=np.asarray(np.ma.filled(np.ma.asarray(a,dtype=np.float32),np.nan))
        return np.where(np.isfinite(a)&(a>=lo)&(a<=hi),a,np.nan).astype(np.float32)
    def save(pid,value,keys,method,levels=(),ps=None,ps_method=None):
        if pid not in requested or value is None:return
        a=np.asarray(value,np.float32)
        good=np.isfinite(a)
        qc={}
        if levels:
            if ps is None or ps.shape!=a.shape:return
            known=np.isfinite(ps)
            eligible=known&(ps>=max(levels)+15.)
            below=known&~eligible
            good &= eligible
            # Missing surface pressure is NOT a terrain exclusion.
            total=a.size;excluded=int(np.count_nonzero(below))
            valid=int(np.count_nonzero(good))
            qc=dict(coverage_basis='terrain_eligible_cells_v1',
                    total_cells=total,terrain_excluded_cells=excluded,
                    pressure_unknown_cells=int(np.count_nonzero(~known)),
                    valid_cells=valid)
        a=np.where(good,a,np.nan)
        if not np.isfinite(a).any():return
        out[pid]=(a,dict(input_variables=sorted(set(keys)),calculation=method,
                         pressure_level_mask=list(levels),surface_pressure_basis=ps_method if levels else None,**qc))
    for pid,key,lo,hi in [('cape','cape',0,15000),('cin','convective_inhibition',-5000,0),('li','lifted_index',-80,80)]:
        if pid in requested:save(pid,get(key,lo,hi),[key],'native Open-Meteo field')
    ps=get('surface_pressure',250,1100);ps_method='native surface_pressure';ps_keys=['surface_pressure']
    if ps is None or not np.isfinite(ps).any():
        msl=get('pressure_msl',800,1150)
        try:hs=validate_grid(source,source.hsurf())
        except (ValueError,TypeError,AttributeError,RuntimeError):hs=None
        if msl is not None and hs is not None:
            hs=np.asarray(hs,np.float32)
            ps=np.where(np.isfinite(hs)&(hs>=-500)&(hs<=9000),
                        msl*np.exp(-hs/8434.),np.nan)
            ps_method='existing MetStat MSLP/orography approximation'
            ps_keys=['pressure_msl','native_model_orography']
        else:ps=None
    T={p:get(f'temperature_{p}hPa',-110,65) for p in LEVELS}
    RH={p:get(f'relative_humidity_{p}hPa',0,100) for p in LEVELS}
    def have(*levels):return all(T[p] is not None and RH[p] is not None for p in levels)
    def keys(levels):return [f'{v}_{p}hPa' for p in levels for v in ('temperature','relative_humidity')]+ps_keys
    # No below-ground replacement on this global product: preserve masks,
    # do not extrapolate Iran-specific surface substitution globally.
    if ps is not None and have(850,700,500):
        lv=(850,700,500);k=keys(lv)
        if 'ki' in requested:save('ki',N.k_index(T,RH),k,'existing k_index',lv,ps,ps_method)
        if 'si' in requested:save('si',N.soaring_index(T,RH),k,'existing soaring_index',lv,ps,ps_method)
    if ps is not None and T[850] is not None and T[500] is not None and RH[850] is not None:
        td=N.td_from_rh(T[850],RH[850]);lv=(850,500)
        k=['temperature_850hPa','temperature_500hPa','relative_humidity_850hPa']+ps_keys
        if 'tt' in requested:save('tt',T[850]+td-2*T[500],k,'existing secondary TT',lv,ps,ps_method)
        if 'shw' in requested:save('shw',S.parcel_to_500(T[850],td,850.,T[500]),k,'existing parcel_to_500',lv,ps,ps_method)
    if ps is not None and 'ko' in requested and have(850,700,500):
        t2=get('temperature_2m',-100,65);rh2=get('relative_humidity_2m',0,100)
        if t2 is not None and rh2 is not None:
            td={p:N.td_from_rh(T[p],RH[p]) for p in (850,700,500)}
            td2=N.td_from_rh(t2,rh2)
            value=.5*(S.theta_e(T[500],td[500],500.)+S.theta_e(T[700],td[700],700.))-.5*(S.theta_e(t2,td2,ps)+S.theta_e(T[850],td[850],850.))
            save('ko',value,keys((850,700,500))+['temperature_2m','relative_humidity_2m'],
                 'existing MetStat surface-based KO (not classic 1000 hPa KO)',(850,700,500),ps,ps_method)
    if ps is not None and 'swt' in requested and T[850] is not None and T[500] is not None and RH[850] is not None:
        winds=[f'wind_{c}_component_{p}hPa' for p in (850,500) for c in ('u','v')]
        v=[get(n,-200,200) for n in winds]
        if all(x is not None for x in v):
            u850,v850,u500,v500=v
            td850=N.td_from_rh(T[850],RH[850]);tt=T[850]+td850-2*T[500]
            f850=np.hypot(u850,v850)*1.94384;f500=np.hypot(u500,v500)*1.94384
            direction=lambda u,v:(np.degrees(np.arctan2(-u,-v))+360)%360
            sh=np.sin(np.radians(direction(u500,v500)-direction(u850,v850)))
            value=12*np.maximum(td850,0)+20*np.maximum(tt-49,0)+2*f850+f500+125*(np.maximum(sh,0)+.2)
            save('swt',value,['temperature_850hPa','temperature_500hPa','relative_humidity_850hPa']+winds+ps_keys,
                 'existing MetStat modified SWEAT', (850,500),ps,ps_method)
    if ps is not None and 'gdi' in requested and have(*LEVELS):
        save('gdi',N.gdi(T,RH,ps),keys(LEVELS),'existing GDI (925 hPa substitution)',LEVELS,ps,ps_method)
    if ps is not None:
        for pid,p in [('lr75',700),('lr85',850)]:
            if pid not in requested or T[p] is None or T[500] is None:continue
            dz=29.27*(.5*(T[p]+T[500])+273.15)*np.log(p/500.)/1000.
            save(pid,(T[p]-T[500])/np.maximum(dz,1.),[f'temperature_{p}hPa','temperature_500hPa']+ps_keys,
                 'existing secondary hypsometric lapse rate',(p,500),ps,ps_method)
        for pid,lower in [('sh85','850hPa'),('sh06','10m')]:
            if pid not in requested:continue
            k=[f'wind_{c}_component_{lev}' for lev in (lower,'500hPa') for c in ('u','v')]
            v=[get(n,-200,200) for n in k]
            if all(x is not None for x in v):
                save(pid,np.hypot(v[2]-v[0],v[3]-v[1]),k+ps_keys,
                     'existing secondary 850–500 shear' if pid=='sh85' else 'existing secondary 10m–500 hPa shear (approx. 0–6 km)',
                     (850,500) if pid=='sh85' else (500,),ps,ps_method)
    if ps is not None and 'li' in requested and 'li' not in out and T[500] is not None:
        t2=get('temperature_2m',-100,65);rh2=get('relative_humidity_2m',0,100)
        if t2 is not None and rh2 is not None:
            save('li',N.lifted_index(t2,rh2,ps,T[500]),
                 ['temperature_2m','relative_humidity_2m','temperature_500hPa']+ps_keys,
                 'existing surface parcel lifted_index',(500,),ps,ps_method)
    return out

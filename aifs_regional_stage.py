"""AIFS Single first regional products using the existing MetStat render engine.

No new host tree or model blending. Native terrain must be directly verified.
The world extent and climatology product remain separate acceptance gates.
"""
from datetime import datetime,timedelta,timezone
from pathlib import Path
from types import SimpleNamespace
import hashlib,json
import numpy as np
import requests
import world_ecmwf_official as W
import nwp_maps as N

MODEL='aifs'
REGION='me'
PARAMS={'pacc':('pr_h24','mm'),'p24':('pr_h24','mm'),'t2m':('temp','°C')}
MAX_TOTAL=16*1024*1024

def palette_contract(manifest):
    params={p['id']:p for p in manifest['params']}
    for p,(scale,unit) in PARAMS.items():
        row=params.get(p,{})
        if row.get('sc')!=scale or row.get('mu',row.get('unit'))!=unit:
            raise ValueError('incompatible existing parameter '+p)
        host=manifest['scales'][scale]; local=N.styles.SC[scale]
        edges=[None if not np.isfinite(x) else float(x) for x in local['edges']]
        if [x.lower() for x in host['c']]!=[x.lower() for x in local['colors']] or host['e']!=edges:
            raise ValueError('palette drift '+scale)
    name=params['t2m']['fa']
    if 'میانگین' in name and ('۲۴' in name or '24' in name):
        return 'mean24'
    if name in ('دمای ۲ متری','دمای ۲ متر'):
        return 'instant'
    raise ValueError('unknown existing T2m time semantics')

def stage(out,manifest,run):
    out=Path(out);mode=palette_contract(manifest)
    if run.utcoffset()!=timedelta(0) or run.hour not in (0,6,12,18) or run.minute or run.second:
        raise ValueError('invalid run')
    # Fixed producer endpoint, two lead times; do not fabricate step zero.
    fields={};refs={}
    with requests.Session() as session:
        def read(key,lead):
            a,m=W.read(session,'aifs-single','0p25',run,lead,key)
            if a.shape!=(721,1440) or m['grid']!=[1440,721] or m['origin']!=[-180,-90] or m['spacing']!=[.25,.25]:
                raise ValueError('AIFS geometry')
            fields[key,lead]=a;refs[f'{key}_{lead}']=m
            return a
        hs=read('orog',0)
        for h in (24,48):read('pacc',h)
        for h in ((6,12,18,24,30,36,42,48) if mode=='mean24' else (24,48)):read('t2m',h)
    if not np.isfinite(hs).all():raise ValueError('native terrain incomplete')
    R=N.MERegion(N.Region('iran'))
    src=SimpleNamespace(dom='aifs_ecmwf_direct',nx=1440,ny=721,lo0=-180.,la0=-90.,dx=.25,dy=.25,i0=0,j0=0,hsurf=lambda:hs)
    st=SimpleNamespace(srcs={'main':src})
    # Reuse the existing approved MetStat correction methods rather than
    # introducing a different precipitation formula. Outside validated DEM
    # explicitly keep the raw interpolated value (no terrain extrapolation).
    engine=object.__new__(N.Engine)
    factor=engine.precip_factor(st,R)
    valid_dem=np.isfinite(R.dem)
    factor=np.where(valid_dem,factor,1.)
    if not np.isfinite(factor).all() or np.min(factor)<=0:raise ValueError('terrain factor')
    report=dict(schema=1,model=MODEL,region=REGION,run=run.strftime('%Y%m%d%H'),mock=False,
                source='ECMWF AIFS Single original Open Data; CC BY 4.0',
                grid=[1440,721],temperature_basis=mode,dem_basis='existing Iran DEM; original fields outside its coverage',
                dem_fraction=float(valid_dem.mean()),factor_min=float(factor.min()),factor_max=float(factor.max()),
                refs=refs,frames=[],pending=['z500a verified climate reference','world extent and full lead timeline'])
    total=0
    for h in (24,48):
        pacc=fields['pacc',h]
        p24=pacc if h==24 else W.daily_precip(pacc,fields['pacc',h-24])
        t=fields['t2m',h] if mode=='instant' else np.mean(np.stack([fields['t2m',j] for j in range(h-18,h+1,6)]),axis=0,dtype=np.float64).astype(np.float32)
        for p,a in [('pacc',pacc),('p24',p24),('t2m',t)]:
            if not np.isfinite(a).all():raise ValueError('incomplete native field '+p)
            raw=R.interp(src,a)
            value=engine.lapse(st,R,lambda:a) if p=='t2m' else np.maximum(raw,0)*factor
            if not np.isfinite(value).all() or (p!='t2m' and np.min(value)<0) or not np.array_equal(value[~valid_dem],raw[~valid_dem]):
                raise ValueError('incorrect terrain correction or coverage')
            # Exact existing palette/render dimensions and physical units.
            b,lines=N.render_me(R,value,PARAMS[p][0])
            if lines is not None:raise ValueError('unexpected overlay')
            vt=run+timedelta(hours=h);f=f'me/{p}_{vt:%Y%m%d%H}.webp'
            dst=out/MODEL/report['run']/f;dst.parent.mkdir(parents=True,exist_ok=True);dst.write_bytes(b)
            total+=len(b)
            report['frames'].append(dict(file=f,param=p,lead=h,valid=vt.strftime('%Y%m%d%H'),sha256=hashlib.sha256(b).hexdigest(),bytes=len(b),
                units=PARAMS[p][1],palette=PARAMS[p][0],min=float(value.min()),max=float(value.max())))
    if total>MAX_TOTAL or len(report['frames'])!=6:raise ValueError('regional stage budget or incomplete batch')
    report['bytes']=total
    (out/'aifs-stage.json').write_text(json.dumps(report,indent=2))
    return report

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--manifest',type=Path,required=True);p.add_argument('--run-utc',required=True)
    a=p.parse_args()
    print(json.dumps(stage(a.out,json.loads(a.manifest.read_text()),datetime.fromisoformat(a.run_utc.replace('Z','+00:00')))),flush=True)

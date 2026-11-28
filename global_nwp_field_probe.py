"""Review-only native global field inventory for expanded NWP products.

Read exact run/lead, one variable group at a time. Do not publish maps, infer
precipitation accumulation windows, or substitute a different model/run.
"""
import argparse
import json
from datetime import timedelta
from pathlib import Path
import numpy as np
from global_nwp_stage import DOMAINS, validate_global_geometry, parse_meta_utc, N
from nwp_unified_resolution import SOURCE_PRIORITY, select_frame_source

GROUPS = {
    'precipitation_native': ('precipitation',),
    'wind10': ('wind_u_component_10m', 'wind_v_component_10m'),
    'wind10_native_speed': ('wind_speed_10m',),
    **{f'z{p}': (f'geopotential_height_{p}hPa',) for p in (850,700,500)},
    **{f't{p}': (f'temperature_{p}hPa',) for p in (850,700,500)},
    **{f'wind{p}': (f'wind_u_component_{p}hPa', f'wind_v_component_{p}hPa')
       for p in (850,700,500,300,250,200)},
}
def inspect_group(source, run, valid, names):
    if not source.exists(run, valid):
        return None
    values = source.read(run, valid, list(names))
    if any(name not in values for name in names):
        return None
    stats = {}
    common = None
    for name in names:
        a = validate_global_geometry(source, values[name])
        mask = np.isfinite(a)
        common = mask if common is None else common & mask
        if float(mask.mean()) < .90:
            return None
        finite = a[mask]
        # No source unit inference or physical unit conversion in this probe.
        stats[name] = {'finite_fraction': float(mask.mean()), 'raw_min': float(finite.min()),
                       'raw_max': float(finite.max())}
    if float(common.mean()) < .90:
        return None
    return {'source_domain': source.dom, 'shape': [source.ny,source.nx],
            'grid_origin': [source.lo0,source.la0], 'grid_spacing': [source.dx,source.dy],
            'joint_finite_fraction': float(common.mean()), 'variables': stats,
            'units_verified': False, 'publication_eligible': False}

def inventory(model, run, lead, sources):
    if run.utcoffset() is None or any((run.minute,run.second,run.microsecond)):
        raise ValueError('exact timezone-aware cycle required')
    if type(lead) is not int or not 0 <= lead <= 384:
        raise ValueError('invalid lead')
    valid = run + timedelta(hours=lead)
    results = {}
    for group,names in GROUPS.items():
        candidates = {}
        for source in sources:
            try:
                result = inspect_group(source,run,valid,names)
                if result is not None:
                    candidates[source.dom] = result
            except (ValueError, RuntimeError, OSError) as e:
                # Preserve explicit per-domain failure without leaking paths.
                candidates[source.dom] = {'error_type': type(e).__name__}
        available = {d:v for d,v in candidates.items() if 'variables' in v}
        if model in SOURCE_PRIORITY:
            choice = select_frame_source(model,names[0],run,valid,
                                         lambda d,v,r,t: d in available)
            selected = choice.domain if choice else None
        else:
            selected = next(iter(available),None)
        results[group] = {'selected_domain': selected, 'candidates': candidates,
                          'status': 'raw-field-available' if selected else 'unavailable'}
        if group == 'precipitation_native':
            results[group]['accumulation_window_verified'] = False
    return {'schema':1,'model':model,'init_utc':run.isoformat(),'valid_utc':valid.isoformat(),
            'lead_hours':lead,'scope':'raw native global field evidence, not products','groups':results}

def main():
    import s3fs
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model',choices=sorted(DOMAINS),required=True)
    p.add_argument('--init-utc',type=parse_meta_utc,required=True)
    p.add_argument('--lead',type=int,required=True)
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args()
    domains=[d for d,_ in SOURCE_PRIORITY[a.model]] if a.model in SOURCE_PRIORITY else [DOMAINS[a.model]]
    if a.model=='gem':
        domains.append('cmc_gem_gdps')
    fs=s3fs.S3FileSystem(anon=True,default_block_size=65536)
    sources=[]
    for domain in domains:
        s=N.S3Source(domain,fs)
        s.full_grid=True
        s.i0,s.i1,s.j0,s.j1=0,s.nx,0,s.ny
        sources.append(s)
    result=inventory(a.model,a.init_utc,a.lead,sources)
    a.out.parent.mkdir(parents=True,exist_ok=True)
    with a.out.open('x',encoding='utf8') as stream:
        json.dump(result,stream,indent=2)
    if not any(x['selected_domain'] for x in result['groups'].values()):
        raise SystemExit(2)

if __name__=='__main__':
    main()

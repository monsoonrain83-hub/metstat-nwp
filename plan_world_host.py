"""Offline plan for the one existing online/data publication tree.

No network or write to cPanel. The world-data branch and temporary catalogs
are staging artifacts only. World raster products are NOT yet interchangeable
with all regional products (e.g. z500 has humidity background regionally).
Do not call begin, end or purge for an independent world staging job.
"""
import hashlib,json,re
from pathlib import Path
from pack_global_products import parse_utc,valid_coverage,CONVECTION_UNITS,VALID_SOURCE_DOMAINS,SOURCE_RESOLUTION

REGION='world'
HOST_ROOT='online/data/nwp'
HOST_MANIFEST='online/data/manifest.json'
PALETTES={p:{'lr75':'lr','lr85':'lr','sh85':'shr','sh06':'shr'}.get(p,p) for p in CONVECTION_UNITS}

def plan(catalog_path,host_manifest):
    """Validate all candidate bytes locally. No placeholder or parallel path.
    Current-run only; absent models/parameters and mismatched runs are deferred.
    """
    path=Path(catalog_path);root=path.parent.resolve()
    catalog=json.loads(path.read_text(encoding='utf8'))
    if catalog.get('schema')!=2 or catalog.get('mock') is not False or catalog.get('world_bounds')!=[-180,-90,180,90]:
        raise ValueError('not a verified multiframe world catalog')
    params={p['id']:p for p in host_manifest['params']}
    records=[];deferred=[];seen=set()
    for model,row in catalog['models'].items():
        if model not in VALID_SOURCE_DOMAINS:raise ValueError('unapproved model')
        run=parse_utc(row['run_utc']).strftime('%Y%m%d%H')
        for p,frames in row['parameters'].items():
            for f in frames:
                if p not in PALETTES or params.get(p,{}).get('sc')!=PALETTES.get(p):
                    deferred.append((model,p,'incompatible or unregistered product'));continue
                if host_manifest.get('models',{}).get(model,{}).get('run')!=run:
                    deferred.append((model,p,'current host cycle mismatch'));continue
                valid=parse_utc(f['valid_utc']).strftime('%Y%m%d%H')
                sha=f.get('sha256','')
                if not re.fullmatch('[a-f0-9]{64}',sha):raise ValueError('bad digest')
                expected=f'{model}/{run}/{p}/{valid}_{sha[:16]}.webp'
                if f['file']!=expected:raise ValueError('unexpected staging path')
                local=root/expected
                if local.resolve()!=local or not local.is_file() or local.stat().st_size>16*1024**2:raise ValueError('unsafe or oversized raster')
                if hashlib.sha256(local.read_bytes()).hexdigest()!=sha:raise ValueError('raster checksum')
                if (f.get('logical_model')!=model or f.get('variable')!=p
                    or f.get('init_utc')!=row['run_utc'] or f.get('palette')!=PALETTES[p]
                    or f.get('units')!=CONVECTION_UNITS[p] or f.get('bbox_wgs84')!=[-180,-90,180,90]
                    or f.get('projection')!='EPSG:4326 equirectangular'
                    or f.get('field_source_domain') not in VALID_SOURCE_DOMAINS[model]
                    or f.get('nominal_resolution')!=SOURCE_RESOLUTION.get(f.get('field_source_domain'))
                    or not valid_coverage(p,f,f['width'],f['height'])):
                    raise ValueError('world provenance mismatch')
                lead=(parse_utc(f['valid_utc'])-parse_utc(f['init_utc'])).total_seconds()/3600
                if lead!=f.get('lead_hours') or lead<0 or lead>384 or lead%6:raise ValueError('wrong lead')
                file=f'{REGION}/{p}_{valid}.webp'
                destination=f'{HOST_ROOT}/{model}/{run}/{file}'
                if destination in seen:raise ValueError('duplicate destination')
                seen.add(destination)
                records.append(dict(model=model,run=run,file=file,source=str(local),
                                    destination=destination,meta=f))
    return dict(records=records,deferred=deferred,manifest=HOST_MANIFEST,deploy=False)

"""Create bounded, immutable multi-frame world catalog from verified source artifacts.

No host writes, no network, no automatic production triggers. Every frame is
validated by the existing global packager, with a single initialization per
logical model. Missing fields are absent, not borrowed from a different run.
"""
from datetime import datetime
from pathlib import Path
import argparse, hashlib, json, os, re, shutil, tempfile
from pack_global_products import EXPECTED_UNITS, VALID_SOURCE_DOMAINS, MODEL_LICENSE, parse_utc, verify_manifest_field

MAX_MANIFESTS=600
DEFAULT_BUDGET=512*1024*1024

def package_frames(source, destination, budget=DEFAULT_BUDGET):
    source,destination=Path(source),Path(destination)
    if type(budget) is not int or not 1<=budget<=2*1024**3:
        raise ValueError('invalid output budget')
    if destination.exists():
        raise FileExistsError('immutable release already exists')
    paths=sorted(source.glob('world-*/manifest.json'))
    if not paths or len(paths)>MAX_MANIFESTS:
        raise ValueError('missing/excess staged frames')
    destination.parent.mkdir(parents=True,exist_ok=True)
    tmp=Path(tempfile.mkdtemp(prefix='.world-release-',dir=destination.parent))
    models={};size=0
    try:
        for path in paths:
            if path.stat().st_size>256*1024:raise ValueError('oversize manifest')
            m=json.loads(path.read_text(encoding='utf8'))
            model=m.get('model')
            if (model not in VALID_SOURCE_DOMAINS or m.get('schema')!=2 or m.get('full_globe') is not True
                or m.get('mock') is not False or m.get('bbox_wgs84')!=[-180,-90,180,90]
                or m.get('projection')!='EPSG:4326 equirectangular'):
                raise ValueError('invalid source manifest')
            run,valid=parse_utc(m['init_utc']),parse_utc(m['valid_utc'])
            if run.minute or valid.minute or run.hour not in (0,6,12,18):
                raise ValueError('invalid run or valid time')
            rid=run.strftime('%Y%m%d%H');vid=valid.strftime('%Y%m%d%H')
            lead=(valid-run).total_seconds()/3600
            if lead<0 or lead>384 or lead%6:
                raise ValueError('unsupported six-hour frame')
            row=models.setdefault(model,dict(run_utc=m['init_utc'],source_license=MODEL_LICENSE[model],parameters={}))
            if row['run_utc']!=m['init_utc']:
                raise ValueError('mixed initialization for model '+model)
            if not isinstance(m.get('fields'),dict) or not m['fields']:
                raise ValueError('no real fields')
            for param,f in m['fields'].items():
                if param not in EXPECTED_UNITS:raise ValueError('unsupported product')
                items=row['parameters'].setdefault(param,[])
                if any(x['valid_utc']==m['valid_utc'] for x in items):
                    raise ValueError('duplicate frame')
                # Bound cumulative bytes before loading and writing each image.
                candidate=path.parent/f'{model}_{param}_{vid}.webp'
                if candidate.stat().st_size>min(32*1024**2,budget-size):
                    raise ValueError('release exceeds byte budget')
                data,sha=verify_manifest_field(model,param,f,m,path.parent)
                size+=len(data)
                if size>budget:raise ValueError('release exceeds byte budget')
                key=f'{model}/{rid}/{param}/{vid}_{sha[:16]}.webp'
                dest=tmp/key;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data)
                items.append({**f,'file':key,'sha256':sha,'bbox_wgs84':[-180,-90,180,90],
                              'projection':'EPSG:4326 equirectangular'})
        for row in models.values():
            for frames in row['parameters'].values():frames.sort(key=lambda f:f['valid_utc'])
        catalog=dict(schema=2,world_bounds=[-180,-90,180,90],projection='EPSG:4326 equirectangular',
                     models=models,available_models=sorted(models),missing_models=sorted(set(VALID_SOURCE_DOMAINS)-set(models)),
                     raster_bytes=size,complete=False,mock=False)
        raw=json.dumps(catalog,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
        if size+len(raw)>budget:raise ValueError('catalog exceeds release budget')
        (tmp/'catalog.json').write_bytes(raw)
        # Destination is new and not an active webroot. No replacement or deletion.
        if destination.exists():raise FileExistsError('destination exists')
        os.rename(tmp,destination)
        return catalog
    finally:
        if tmp.exists():shutil.rmtree(tmp)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('source',type=Path);p.add_argument('destination',type=Path)
    p.add_argument('--budget-bytes',type=int,default=DEFAULT_BUDGET)
    args=p.parse_args();c=package_frames(args.source,args.destination,args.budget_bytes)
    print(json.dumps({k:c[k] for k in ('available_models','missing_models','raster_bytes','complete')}))

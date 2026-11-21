#!/usr/bin/env python3
"""Publish only verified world forecasts to a stable asset catalog (offline operation)."""
import json, hashlib, shutil, sys
from pathlib import Path

def package(src:Path,dest:Path):
    models={}
    for folder in sorted(src.glob('world-*')):
        mp=folder/'manifest.json'
        if not mp.is_file():continue
        man=json.loads(mp.read_text(encoding='utf8'))
        model=man.get('model')
        if model not in ('gfs','ecmwf','gem') or not man.get('full_globe') or man.get('mock'):
            raise ValueError('untrusted or non-world manifest: '+str(mp))
        if man.get('bbox_wgs84')!=[-180.0,-90.0,180.0,90.0] or man.get('projection')!='EPSG:4326 equirectangular':
            raise ValueError('incorrect global georeferencing')
        if not man.get('fields'):raise ValueError('no real fields for '+model)
        md=dest/model;md.mkdir(parents=True,exist_ok=True);fields={}
        for p,x in man['fields'].items():
            if p not in ('t2m','z500','mslp'):raise ValueError('unexpected variable '+p)
            f=folder/x['file']
            if not f.is_file() or f.stat().st_size<100:raise ValueError('missing real raster '+str(f))
            if x['finite_fraction']<.90 or x['width']<720 or x['height']<360:
                raise ValueError('incomplete global raster '+str(f))
            data=f.read_bytes()
            if data[:4]!=b'RIFF' or data[8:12]!=b'WEBP':raise ValueError('not real WebP')
            destpath=md/(p+'.webp');destpath.write_bytes(data)
            fields[p]={**x,'file':model+'/'+p+'.webp','sha256':hashlib.sha256(data).hexdigest()}
        meta={**man,'fields':fields}
        (md/'manifest.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf8')
        models[model]=meta
    if set(models)!=set(('gfs','ecmwf','gem')):
        raise RuntimeError('missing mandatory model from verified artifacts: '+repr(set(models)))
    catalog={'schema':1,'source':'real model fields through Open-Meteo data_spatial / respective NWP center',
             'license':'CC BY 4.0 with attribution','world_bounds':[-180,-90,180,90],
             'image_base':'world/','models':models,'complete':True,'mock':False}
    dest.mkdir(parents=True,exist_ok=True)
    (dest/'catalog.json').write_text(json.dumps(catalog,ensure_ascii=False,indent=2),encoding='utf8')
    print('WORLD_CATALOG_PUBLISHED',json.dumps({m:list(x['fields']) for m,x in models.items()}),flush=True)
    return catalog

if __name__=='__main__':package(Path(sys.argv[1]),Path(sys.argv[2]))

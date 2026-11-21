#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage *real* global NWP fields; independent of Iran/ME production and host uploader.
No map or run is published to the live site by this program.
Each artifact includes the native global equirectangular raster and manifest with
true geographic envelope, model, cycle, valid-time, variable and source licence.
"""
import argparse
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
import nwp_maps as N

UTC = timezone.utc
DOMAINS = {
    'gfs': 'ncep_gfs025',          # globally 0.25°, distinct from regional GFS013
    'ecmwf': 'ecmwf_ifs025',      # globally 0.25°
    'gem': 'cmc_gem_gdps_15km',   # globally 0.15°, may be unavailable on S3
}
FIELDS = {
    't2m': ('temperature_2m', '°C', -60.0, 50.0),
    'z500': ('geopotential_height_500hPa', 'dam', 480.0, 610.0),
    'mslp': ('pressure_msl', 'hPa', 960.0, 1060.0),
}
PALETTE = [
    '#20278f','#244fbc','#317bd1','#53acc9','#8dcac9','#d0e3ce',
    '#f6e7a9','#f2bf72','#e99651','#d75f43','#b8313d','#751b4e',
]
def to_units(param, field):
    a = np.asarray(field, np.float32)
    good = a[np.isfinite(a)]
    if good.size == 0: raise ValueError(param + ': all missing')
    med = float(np.median(good))
    if param == 't2m':
        if med > 130: a = a - 273.15
        if not (-110 < float(np.nanmedian(a)) < 65): raise ValueError('unphysical T2m')
    elif param == 'z500':
        if med > 1500: a = a / 10.0
        if not (350 < float(np.nanmedian(a)) < 670): raise ValueError('unphysical Z500')
    elif param == 'mslp':
        if med > 3000: a = a / 100.0
        if not (850 < float(np.nanmedian(a)) < 1120): raise ValueError('unphysical MSLP')
    return a

def render(field, param, dest):
    a = to_units(param, field)
    lo, hi = FIELDS[param][2:]
    bins = np.floor((a - lo) / (hi - lo) * len(PALETTE))
    idx = np.clip(np.nan_to_num(bins, nan=0).astype(np.int16), 0, len(PALETTE)-1)
    pal = np.array([tuple(bytes.fromhex(c[1:])) for c in PALETTE], np.uint8)
    rgb = pal[idx]
    rgb[~np.isfinite(a)] = [215,215,215]
    # Source array is latitude south-to-north. North MUST appear at image top.
    im = Image.fromarray(np.flipud(rgb), 'RGB')
    im.save(dest, format='WEBP', lossless=True, method=4)
    return {'width':im.width,'height':im.height,'finite_fraction':round(float(np.isfinite(a).mean()),5),
            'min':round(float(np.nanmin(a)),2),'max':round(float(np.nanmax(a)),2)}

def product_manifest(model, run, valid, dom, result):
    return {'schema':1,'model':model,'source_domain':dom,'source':'Open-Meteo data_spatial / model owner',
            'license':'CC BY 4.0; attribution Open-Meteo and originating NWP center',
            'init_utc':run.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'valid_utc':valid.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'projection':'EPSG:4326 equirectangular','bbox_wgs84':[-180.0,-90.0,180.0,90.0],
            'longitude_orientation':'west_to_east','latitude_orientation':'north_to_south',
            'fields':result,'full_globe':True,'mock':False}

def resolve_cycle(meta):
    return datetime.strptime(meta['reference_time'][:16],'%Y-%m-%dT%H:%M').replace(tzinfo=UTC)

def valid_candidates(meta, run, requested_lead=24):
    out = []
    for s in meta.get('valid_times',[]):
        try:
            vt = datetime.strptime(s[:16],'%Y-%m-%dT%H:%M').replace(tzinfo=UTC)
        except ValueError: continue
        hours = (vt-run).total_seconds()/3600
        if 0 <= hours <= 120:out.append((abs(hours-requested_lead),vt))
    return [v for _,v in sorted(out)]

def acquire(model, outdir, requested_lead=24):
    import s3fs
    dom = DOMAINS[model]
    fs = s3fs.S3FileSystem(anon=True, default_block_size=65536)
    src = N.S3Source(dom, fs)
    # Intentional global override of the existing regional BBOX subsetting;
    # do NOT mutate N.BBOX or production Engine's model loops.
    src.i0=0;src.i1=src.nx;src.j0=0;src.j1=src.ny
    runs = [x for x in src.runs() if x and x.get('reference_time')]
    if not runs:raise RuntimeError(model+': source has no current cycle')
    runs.sort(key=lambda m:m['reference_time'],reverse=True)
    outdir.mkdir(parents=True,exist_ok=True)
    errors=[]
    for meta in runs:
        run = resolve_cycle(meta)
        for valid in valid_candidates(meta, run, requested_lead)[:5]:
            if not src.exists(run,valid):continue
            try: data = src.read(run, valid, sorted(v[0] for v in FIELDS.values()))
            except Exception as e:
                errors.append(str(e)[:120]);continue
            # On GFS, the coarse pressure-level archive may omit T2m. The
            # independent GFS013 surface archive contains the actual field.
            # Resample nearest onto the precisely georeferenced 0.25° world grid.
            if model == 'gfs' and 'temperature_2m' not in data:
                try:
                    surface=N.S3Source('ncep_gfs013',fs)
                    surface.i0=0;surface.i1=surface.nx;surface.j0=0;surface.j1=surface.ny
                    if surface.exists(run,valid):
                        raw=surface.read(run,valid,['temperature_2m']).get('temperature_2m')
                        if raw is not None and raw.shape==(surface.ny,surface.nx):
                            ilon=np.clip(np.rint((src.lo0+np.arange(src.nx)*src.dx-surface.lo0)/surface.dx).astype(int),0,surface.nx-1)
                            ilat=np.clip(np.rint((src.la0+np.arange(src.ny)*src.dy-surface.la0)/surface.dy).astype(int),0,surface.ny-1)
                            data['temperature_2m']=raw[np.ix_(ilat,ilon)]
                            print('GFS_REAL_SURFACE_FALLBACK ncep_gfs013 -> 0.25deg',flush=True)
                except Exception as e:errors.append('GFS T2m alternate source: '+str(e)[:120])
            products={}
            for p,(key,units,lo,hi) in FIELDS.items():
                arr=data.get(key)
                if arr is None:continue
                if arr.ndim!=2 or arr.shape!=(src.ny,src.nx):
                    errors.append(f'{p}: incorrect raster shape {arr.shape}');continue
                # Some fields have valid physical gaps; require nearly global coverage.
                if np.isfinite(arr).mean() < .90:
                    errors.append(f'{p}: only {np.isfinite(arr).mean():.1%} valid');continue
                try:
                    fname=f'{model}_{p}_{valid:%Y%m%d%H}.webp'
                    stats=render(arr,p,outdir/fname)
                    products[p]={'file':fname,'variable':key,'units':units,**stats}
                except Exception as e:errors.append(f'{p}: {e}')
            if products:
                man=product_manifest(model,run,valid,dom,products)
                (outdir/'manifest.json').write_text(json.dumps(man,ensure_ascii=False,indent=2),encoding='utf-8')
                print('GLOBAL_REAL_PRODUCED',json.dumps({'model':model,'run':man['init_utc'],'valid':man['valid_utc'],
                      'products':list(products),'shapes':{p:[q['width'],q['height']] for p,q in products.items()}},ensure_ascii=False),flush=True)
                return man
    raise RuntimeError(model+': no valid global arrays available: '+str(errors[:8]))

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--model',choices=sorted(DOMAINS),required=True)
    p.add_argument('--out',required=True)
    p.add_argument('--lead',type=int,default=24)
    a=p.parse_args()
    acquire(a.model,Path(a.out),a.lead)
if __name__=='__main__': main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage *real* global NWP fields; independent of Iran/ME production and host uploader.
No map or run is published to the live site by this program.
Each artifact includes the native global equirectangular raster and manifest with
true geographic envelope, model, cycle, valid-time, variable and source licence.
"""
import argparse
import hashlib
import json
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
import nwp_maps as N
from nwp_unified_resolution import select_frame_source, SOURCE_PRIORITY

UTC = timezone.utc
DOMAINS = {
    'gfs': 'ncep_gfs025',          # globally 0.25°, distinct from regional GFS013
    'ecmwf': 'ecmwf_ifs025',      # globally 0.25°
    'gem': 'cmc_gem_gdps_15km',   # globally 0.15°, may be unavailable on S3
    'icon': 'dwd_icon',            # global 0.125° regular grid; never ICON-EU
    'ukmo': 'ukmo_global_deterministic_10km', # global 10km source
}
# Nominal labels are SOURCE claims, never inferred from the requested region.
NOMINAL_SINGLE_SOURCE = {'gem':'15 km', 'icon':'13 km', 'ukmo':'10 km'}
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
    # Root source must never claim coarse 28km when a high-resolution raster
    # was actually rendered; variable-level source is authoritative.
    sources={v.get('field_source_domain') for v in result.values()
             if v.get('field_source_domain')}
    root_source=next(iter(sources)) if len(sources)==1 else ('mixed-per-field' if sources else dom)
    return {'schema':2,'model':model,'source_domain':root_source,'source':'Open-Meteo data_spatial / model owner',
            'license':'CC BY 4.0; attribution Open-Meteo and originating NWP center',
            'generated_at_utc':datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'init_utc':run.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'valid_utc':valid.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'projection':'EPSG:4326 equirectangular','bbox_wgs84':[-180.0,-90.0,180.0,90.0],
            'longitude_orientation':'west_to_east','latitude_orientation':'north_to_south',
            'fields':result,'full_globe':True,'mock':False}

def parse_meta_utc(token):
    """Parse full source timestamp; normalize explicit offsets before cycle joins.

    Open-Meteo's timezone-less metadata is defined as UTC. Never truncate a
    suffix: doing so mislabels +03:30 as UTC and can merge different cycles.
    Reject malformed or sub-minute timestamps instead of inventing an hour.
    """
    if not isinstance(token, str) or len(token) < 16 or token[10] != 'T':
        raise ValueError('NWP timestamp must include an ISO date and time')
    dt = datetime.fromisoformat(
        token[:-1] + '+00:00' if token.endswith('Z') else token)
    if dt.second or dt.microsecond:
        raise ValueError('NWP timestamp must be aligned to a whole minute')
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def resolve_cycle(meta):
    return parse_meta_utc(meta['reference_time'])


def valid_candidates(meta, run, requested_lead=24):
    """Return only the EXACT requested lead, never a nearest-hour substitute.

    This stage publishes an explicitly requested forecast hour. If that hour
    is missing, a different lead must not be silently rendered in its place.
    """
    if type(requested_lead) is not int or not 0 <= requested_lead <= 384:
        raise ValueError('forecast lead must be an integer from 0 to 384 hours')
    requested_valid = run + timedelta(hours=requested_lead)
    for token in meta.get('valid_times', []) or []:
        try:
            valid = parse_meta_utc(token)
        except (ValueError, TypeError):
            continue
        if valid == requested_valid:
            return [valid]
    return []


def validate_global_geometry(source, raw):
    """Reject regional or misregistered grids before claiming global coverage.

    The nominal source grid must span the anti-meridian and reach both poles
    within half-cell georeferencing tolerance; dimensions alone are not proof.
    """
    array = np.asarray(raw)
    if array.ndim != 2 or array.shape != (source.ny, source.nx):
        raise ValueError(f'wrong global grid shape: {array.shape}')
    if source.nx < 720 or source.ny < 360:
        raise ValueError('insufficient resolution for world raster')
    coords = np.asarray([source.lo0, source.la0, source.dx, source.dy], dtype=float)
    if not np.isfinite(coords).all() or source.dx <= 0 or source.dy <= 0:
        raise ValueError('non-finite or non-monotonic global grid geometry')
    west_edge = source.lo0 - source.dx / 2
    east_edge = source.lo0 + (source.nx - 0.5) * source.dx
    south_edge = source.la0 - source.dy / 2
    north_edge = source.la0 + (source.ny - 0.5) * source.dy
    if any(abs(actual - expected) > 0.3 for actual, expected in (
        (west_edge, -180), (east_edge, 180),
        (south_edge, -90), (north_edge, 90),
    )):
        raise ValueError('grid geographic bounds do not cover entire globe')
    return array

def read_independent_sources(sources, run, valid, fields, errors):
    """Fetch each actual source independently; failure of one cannot hide another."""
    result = {}
    for candidate in sources:
        if candidate is None: continue
        try:
            if not candidate.exists(run, valid): continue
            values = candidate.read(run, valid, fields)
            if not isinstance(values, dict):
                raise ValueError('source returned no field dictionary')
            result[candidate.dom] = values
        except Exception as exc:
            errors.append(f'{candidate.dom}: {str(exc)[:150]}')
    return result

def cycle_candidates(*sources):
    """Union actual cycle/valid-hour metadata across independently available grids.

    Neither 28km metadata nor high-resolution metadata is a prerequisite for
    trying the other grid. Merge only IDENTICAL UTC initialization timestamps;
    never re-label a field with a different cycle or valid time.
    """
    merged = {}
    for source in sources:
        if source is None:
            continue
        try:
            items = source.runs()
        except Exception:
            continue
        for item in items or []:
            if not isinstance(item, dict) or not item.get('reference_time'):
                continue
            try:
                run = resolve_cycle(item)
            except (ValueError, TypeError, KeyError):
                continue
            times = merged.setdefault(run, set())
            for token in item.get('valid_times', []) or []:
                if not isinstance(token, str):
                    continue
                try:
                    vt = parse_meta_utc(token)
                except (ValueError, TypeError):
                    continue
                if 0 <= (vt - run).total_seconds() <= 384 * 3600:
                    times.add(vt.strftime('%Y-%m-%dT%H:%M'))
    return [
        {'reference_time': run.strftime('%Y-%m-%dT%H:%M'),
         'valid_times': sorted(times)}
        for run, times in sorted(merged.items(), reverse=True) if times
    ]


def acquire(model, outdir, requested_lead=24, required_run=None):
    import s3fs
    dom = DOMAINS[model]
    fs = s3fs.S3FileSystem(anon=True, default_block_size=65536)
    src = N.S3Source(dom, fs)
    # Intentional global override of the existing regional BBOX subsetting;
    # do NOT mutate N.BBOX or production Engine's model loops.
    src.i0=0;src.i1=src.nx;src.j0=0;src.j1=src.ny
    # The native high-resolution source is optional, never a prerequisite to
    # rendering a verified 0.25-degree fallback at the SAME cycle and lead.
    hi_src = None
    if model in SOURCE_PRIORITY:
        high_domain = SOURCE_PRIORITY[model][0][0]
        hi_src = N.S3Source(high_domain, fs)
        hi_src.i0=0;hi_src.i1=hi_src.nx;hi_src.j0=0;hi_src.j1=hi_src.ny
    runs = cycle_candidates(src, hi_src)
    if required_run is not None:
        runs = [m for m in runs if resolve_cycle(m) == required_run]
    if not runs:raise RuntimeError(model+': source has no current cycle')
    runs.sort(key=lambda m:m['reference_time'],reverse=True)
    outdir.mkdir(parents=True,exist_ok=True)
    errors=[]
    for meta in runs:
        run = resolve_cycle(meta)
        for valid in valid_candidates(meta, run, requested_lead)[:5]:
            # Source availability is independent: a missing 0.25-degree field
            # must not prevent using a verified 9/13km field at the same cycle.
            # Never mix runs or substitute a different valid time.
            source_fields = read_independent_sources(
                (src, hi_src), run, valid, sorted(v[0] for v in FIELDS.values()), errors)
            data = source_fields.get(src.dom, {})
            high_data = source_fields.get(hi_src.dom, {}) if hi_src else {}
            if not data and not high_data: continue
            # A source is selectable only after actual field read + shape and
            # coverage QC. Prefer each variable at native 9/13km independently.
            products={}
            for p,(key,units,lo,hi) in FIELDS.items():
                verified = {}
                source_instances = {}
                # Read and validate both candidate rasters separately. We NEVER
                # present 28km data as a 9km raster or count both as two models.
                for source, raw in ((src, data.get(key)),
                                    (hi_src, high_data.get(key))):
                    if source is None or raw is None: continue
                    try:
                        raw = validate_global_geometry(source, raw)
                    except (ValueError, TypeError, AttributeError) as exc:
                        errors.append(f'{source.dom}/{p}: {exc}')
                        continue
                    if float(np.isfinite(raw).mean()) < .90:
                        errors.append(f'{source.dom}/{p}: insufficient global coverage');continue
                    try: to_units(p,raw)
                    except Exception as e: errors.append(f'{source.dom}/{p}: {e}');continue
                    verified[source.dom] = raw
                    source_instances[source.dom] = source
                if model in SOURCE_PRIORITY:
                    choice = select_frame_source(model,key,run,valid,
                        lambda d,v,r,t: d in verified)
                    if choice is None: continue
                    chosen_domain, nominal_resolution = choice.domain,choice.nominal_resolution
                elif dom in verified:
                    chosen_domain,nominal_resolution=dom,NOMINAL_SINGLE_SOURCE[model]
                else: continue
                arr=verified[chosen_domain]
                chosen_src=source_instances[chosen_domain]
                try:
                    fname=f'{model}_{p}_{valid:%Y%m%d%H}.webp'
                    raster_path=outdir/fname
                    stats=render(arr,p,raster_path)
                    # Hash the actual rendered bytes, not an unverified source URL.
                    output_sha256=hashlib.sha256(raster_path.read_bytes()).hexdigest()
                    source_bounds=[chosen_src.lo0,chosen_src.la0,
                        chosen_src.lo0+chosen_src.dx*(chosen_src.nx-1),
                        chosen_src.la0+chosen_src.dy*(chosen_src.ny-1)]
                    products[p]={'file':fname,'variable':key,'units':units,
                                 'sha256':output_sha256,
                                 'logical_model':model,
                                 'init_utc':run.strftime('%Y-%m-%dT%H:%M:%SZ'),
                                 'valid_utc':valid.strftime('%Y-%m-%dT%H:%M:%SZ'),
                                 'lead_hours':int((valid-run).total_seconds()/3600),
                                 'source_grid_bbox_centers_wgs84':source_bounds,
                                 'field_source_domain':chosen_domain,
                                 'nominal_resolution':nominal_resolution,
                                 'source_grid':[chosen_src.nx,chosen_src.ny],
                                 'source_grid_origin':[chosen_src.lo0,chosen_src.la0],
                                 'source_grid_spacing':[chosen_src.dx,chosen_src.dy],
                                 'resampling':('octahedral-O1280-to-regular-grid' if chosen_domain=='ecmwf_ifs' else 'native-source-grid'),
                                 **stats}
                except Exception as e: errors.append(f'{p}: {e}')
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
    p.add_argument('--run-utc', help='Require this exact source cycle (ISO UTC); never fall back to a different run')
    a=p.parse_args()
    acquire(a.model,Path(a.out),a.lead,parse_meta_utc(a.run_utc) if a.run_utc else None)
if __name__=='__main__': main()

#!/usr/bin/env python3
"""Publish only verified world forecasts to a stable asset catalog (offline operation)."""
import json, hashlib, shutil, sys
from datetime import datetime, timezone
from pathlib import Path

VALID_SOURCE_DOMAINS = {
    'ecmwf': {'ecmwf_ifs', 'ecmwf_ifs025'},
    'gfs': {'ncep_gfs013', 'ncep_gfs025'},
    'gem': {'cmc_gem_gdps_15km', 'cmc_gem_gdps'},
    'icon': {'dwd_icon'},
    'ukmo': {'ukmo_global_deterministic_10km'},
}
SOURCE_RESOLUTION = {
    'ecmwf_ifs':'9 km','ecmwf_ifs025':'28 km',
    'ncep_gfs013':'13 km','ncep_gfs025':'28 km',
    'cmc_gem_gdps_15km':'15 km','cmc_gem_gdps':'15 km',
    'dwd_icon':'13 km','ukmo_global_deterministic_10km':'10 km',
}
MODEL_LICENSE = {
    'ecmwf':'CC BY 4.0 with ECMWF/Open-Meteo attribution',
    'gfs':'Open-Meteo data CC BY 4.0; NOAA NCEP attribution',
    'gem':'Open-Meteo data CC BY 4.0; ECCC CMC attribution',
    'icon':'CC BY 4.0 with DWD/Open-Meteo attribution',
    'ukmo':'CC BY-SA 4.0 — UK Met Office; adaptations share alike',
}

EXPECTED_UNITS = {'t2m': '°C', 'z500': 'dam', 'mslp': 'hPa'}


def parse_utc(value):
    if not isinstance(value, str) or not value.endswith('Z'):
        raise ValueError('forecast timestamp requires explicit UTC/Z')
    timestamp = datetime.fromisoformat(value[:-1] + '+00:00')
    if timestamp.second or timestamp.microsecond:
        raise ValueError('forecast timestamp must be minute-aligned')
    return timestamp.astimezone(timezone.utc)


def verify_manifest_field(model, param, field, man, folder):
    """Require real same-cycle, global, physically classified WebP bytes."""
    if not isinstance(field, dict):
        raise ValueError('invalid field manifest')
    run = parse_utc(man.get('init_utc'))
    valid = parse_utc(man.get('valid_utc'))
    lead = (valid - run).total_seconds() / 3600
    if lead < 0 or lead != int(lead) or lead > 384:
        raise ValueError('invalid global forecast lead')
    if (field.get('logical_model') != model or
            field.get('init_utc') != man['init_utc'] or
            field.get('valid_utc') != man['valid_utc'] or
            type(field.get('lead_hours')) is not int or field['lead_hours'] != int(lead)):
        raise ValueError('field cycle/valid/lead mismatch: ' + model + '/' + param)
    if field.get('field_source_domain') not in VALID_SOURCE_DOMAINS[model]:
        raise ValueError('field source differs from logical model')
    if field.get('nominal_resolution') != SOURCE_RESOLUTION[field.get('field_source_domain')]:
        raise ValueError('source raster resolution label mismatch')
    if field.get('units') != EXPECTED_UNITS[param]:
        raise ValueError('field unit mismatch')
    # No directory traversals, absolute paths or arbitrary local file reads.
    expected_name = f'{model}_{param}_{valid:%Y%m%d%H}.webp'
    if field.get('file') != expected_name:
        raise ValueError('unexpected raster filename: ' + str(field.get('file')))
    frame = folder / expected_name
    if not frame.is_file() or frame.stat().st_size < 100:
        raise ValueError('missing real raster: ' + str(frame))
    w, h = field.get('width'), field.get('height')
    if type(w) is not int or type(h) is not int or w < 720 or h < 360:
        raise ValueError('insufficient raster size')
    grid = field.get('source_grid')
    origin = field.get('source_grid_origin')
    spacing = field.get('source_grid_spacing')
    if grid != [w, h] or not isinstance(origin, list) or not isinstance(spacing, list) or len(origin) != 2 or len(spacing) != 2:
        raise ValueError('source grid and image size mismatch')
    from math import isfinite
    try:
        lon, lat = map(float, origin)
        dx, dy = map(float, spacing)
    except (TypeError, ValueError) as exc:
        raise ValueError('invalid source grid coordinates') from exc
    if not all(map(isfinite, (lon, lat, dx, dy))) or dx <= 0 or dy <= 0:
        raise ValueError('invalid source grid coordinates')
    bounds = (lon - dx / 2, lon + (w - .5) * dx,
              lat - dy / 2, lat + (h - .5) * dy)
    if any(abs(value - target) > .3 for value, target in
           zip(bounds, (-180, 180, -90, 90))):
        raise ValueError('source grid is not global')
    fraction = field.get('finite_fraction')
    if type(fraction) not in (int, float) or not isfinite(fraction) or not .90 <= fraction <= 1:
        raise ValueError('insufficient global valid pixels')
    data = frame.read_bytes()
    if (data[:4] != b'RIFF' or data[8:12] != b'WEBP' or
            int.from_bytes(data[4:8], 'little') != len(data) - 8):
        raise ValueError('corrupt or truncated WebP payload')
    checksum = hashlib.sha256(data).hexdigest()
    if field.get('sha256') != checksum:
        raise ValueError('source raster checksum mismatch')
    return data, checksum

def package(src:Path,dest:Path):
    models={}
    for folder in sorted(src.glob('world-*')):
        mp=folder/'manifest.json'
        if not mp.is_file():continue
        man=json.loads(mp.read_text(encoding='utf8'))
        model=man.get('model')
        if model not in ('gfs','ecmwf','gem','icon','ukmo') or not man.get('full_globe') or man.get('mock'):
            raise ValueError('untrusted or non-world manifest: '+str(mp))
        if man.get('bbox_wgs84')!=[-180.0,-90.0,180.0,90.0] or man.get('projection')!='EPSG:4326 equirectangular':
            raise ValueError('incorrect global georeferencing')
        if man.get('schema') != 2:
            raise ValueError('world manifest must carry schema-2 source provenance')
        if not isinstance(man.get('fields'), dict) or not man['fields']:
            raise ValueError('no real fields for '+model)
        if model in models:
            raise ValueError('duplicate model artifact: '+model)
        md=dest/model;md.mkdir(parents=True,exist_ok=True);fields={}
        for p,x in man['fields'].items():
            if p not in EXPECTED_UNITS:raise ValueError('unexpected variable '+p)
            data, checksum = verify_manifest_field(model, p, x, man, folder)
            destpath=md/(p+'.webp');destpath.write_bytes(data)
            fields[p]={**x,'file':model+'/'+p+'.webp','sha256':checksum}
        meta={**man,'fields':fields,'source_license':MODEL_LICENSE[model]}
        (md/'manifest.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf8')
        models[model]=meta
    if set(models)!=set(('gfs','ecmwf','gem','icon','ukmo')):
        raise RuntimeError('missing mandatory model from verified artifacts: '+repr(set(models)))
    missing_fields={m:sorted(set(EXPECTED_UNITS)-set(v['fields'])) for m,v in models.items()}
    fields_complete=not any(missing_fields.values())
    catalog={'schema':1,'source':'real model fields through Open-Meteo data_spatial / respective NWP center',
             'license':'Mixed model-specific licences; UKMO forecasts CC BY-SA 4.0; see models.source_license','world_bounds':[-180,-90,180,90],
             'image_base':'world/','models':models,'complete':fields_complete,'models_complete':True,
             'coverage':{'scope':'single-lead baseline fields only','expected_fields':sorted(EXPECTED_UNITS),
                         'missing_fields':missing_fields,'fields_complete':fields_complete,
                         'lead_hours_by_model':{m:sorted({x['lead_hours'] for x in v['fields'].values()}) for m,v in models.items()}},
             'mock':False}
    dest.mkdir(parents=True,exist_ok=True)
    (dest/'catalog.json').write_text(json.dumps(catalog,ensure_ascii=False,indent=2),encoding='utf8')
    print('WORLD_CATALOG_PUBLISHED',json.dumps({m:list(x['fields']) for m,x in models.items()}),flush=True)
    return catalog

if __name__=='__main__':package(Path(sys.argv[1]),Path(sys.argv[2]))

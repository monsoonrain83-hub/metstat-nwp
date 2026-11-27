#!/usr/bin/env python3
"""Publish only verified world forecasts to a stable asset catalog (offline operation)."""
import json, hashlib, shutil, sys
from datetime import datetime, timezone
from pathlib import Path
from nwp_source_policy import ECCC_DOMAIN, ECCC_LICENCE
import world_gem_official as GO

VALID_SOURCE_DOMAINS = {
    'ecmwf': {'ecmwf_ifs', 'ecmwf_ifs025'},
    'gfs': {'ncep_gfs013', 'ncep_gfs025'},
    'gem': {'cmc_gem_gdps_15km', 'cmc_gem_gdps', ECCC_DOMAIN},
    'icon': {'dwd_icon'},
    'ukmo': {'ukmo_global_deterministic_10km'},
}
SOURCE_RESOLUTION = {
    'ecmwf_ifs':'9 km','ecmwf_ifs025':'28 km',
    'ncep_gfs013':'13 km','ncep_gfs025':'28 km',
    'cmc_gem_gdps_15km':'15 km','cmc_gem_gdps':'15 km',ECCC_DOMAIN:'15 km',
    'dwd_icon':'13 km','ukmo_global_deterministic_10km':'10 km',
}
MODEL_LICENSE = {
    'ecmwf':'CC BY 4.0 with ECMWF/Open-Meteo attribution',
    'gfs':'Open-Meteo data CC BY 4.0; NOAA NCEP attribution',
    'gem':'ECCC original data or Open-Meteo CC BY 4.0; see per-field source licence and attribution',
    'icon':'CC BY 4.0 with DWD/Open-Meteo attribution',
    'ukmo':'CC BY-SA 4.0 — UK Met Office; adaptations share alike',
}

CONVECTION_UNITS = {'cape':'J/kg','cin':'J/kg','li':'K','ki':'K','si':'K','tt':'K','gdi':'',
                    'shw':'K','lr75':'K/km','lr85':'K/km','sh85':'m/s','sh06':'m/s','ko':'K','swt':'','refl':'dBZ','sigwx':''}
EXPECTED_UNITS = {'t2m': '°C', 'z500': 'dam', 'mslp': 'hPa', **CONVECTION_UNITS}


def parse_utc(value):
    if not isinstance(value, str) or not value.endswith('Z'):
        raise ValueError('forecast timestamp requires explicit UTC/Z')
    timestamp = datetime.fromisoformat(value[:-1] + '+00:00')
    if timestamp.second or timestamp.microsecond:
        raise ValueError('forecast timestamp must be minute-aligned')
    return timestamp.astimezone(timezone.utc)


# Only these pressure-level products may discount physically excluded cells.
TERRAIN_LEVELS = {'ki':850,'si':850,'tt':850,'shw':850,'gdi':925,'ko':850,'swt':850,
                  'lr75':700,'lr85':850,'sh85':850,'sh06':500,'li':500}

def valid_coverage(param, field, width, height):
    """90% of terrain-eligible cells, counting unknown pressure as missing.
    Never waive the ordinary 90% gate for unmasked products. Counts describe
    the producer's QC, not independent verification of the input fields.
    """
    from math import isfinite
    fraction=field.get('finite_fraction')
    if type(fraction) not in (int,float) or not isfinite(fraction) or not 0<=fraction<=1:
        return False
    if field.get('coverage_basis') is None:
        return fraction>=.90 and not field.get('pressure_level_mask')
    if field.get('coverage_basis')!='terrain_eligible_cells_v1' or param not in TERRAIN_LEVELS:
        return False
    levels=field.get('pressure_level_mask')
    if not isinstance(levels,list) or not levels or any(type(x) is not int or x not in (500,700,850,925) for x in levels):
        return False
    if max(levels)!=TERRAIN_LEVELS[param] or not field.get('surface_pressure_basis'):
        return False
    counts=[field.get(k) for k in ('total_cells','terrain_excluded_cells','pressure_unknown_cells','valid_cells')]
    if any(type(x) is not int or x<0 for x in counts):return False
    total,excluded,unknown,valid=counts
    if total!=width*height or total<=0 or excluded+unknown+valid>total:return False
    # Conservative global floor: do not accept an apparently regional product
    # disguised by declaring most of the globe beneath a pressure surface.
    if excluded>.30*total or abs(fraction-valid/total)>.0000051:return False
    return valid>=.90*(total-excluded)


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
    if field.get('field_source_domain')==ECCC_DOMAIN:
        refs=field.get('source_fields')
        dependencies=field.get('input_variables') if param in CONVECTION_UNITS else [field.get('variable')]
        if (field.get('distribution')!='producer' or field.get('source_licence')!=ECCC_LICENCE
            or not isinstance(refs,dict) or not isinstance(dependencies,list) or not dependencies
            or any(not isinstance(k,str) or k not in GO.FIELDS for k in dependencies)
            or set(refs)!=set(dependencies)):
            raise ValueError('official GDPS provenance missing')
        for key,ref in refs.items():
            if (not isinstance(ref,dict) or ref.get('status')!='verified'
                or ref.get('source_url')!=GO.field_url(run,valid,key)
                or ref.get('grid')!=[GO.NX,GO.NY] or ref.get('origin')!=[-180,-90] or ref.get('spacing')!=[.15,.15]):
                raise ValueError('official GDPS source metadata mismatch')
    if param in CONVECTION_UNITS:
        palette={'lr75':'lr','lr85':'lr','sh85':'shr','sh06':'shr'}.get(param,param)
        if (field.get('palette')!=palette or not isinstance(field.get('calculation'),str)
            or not field['calculation'] or not isinstance(field.get('input_variables'),list)
            or not field['input_variables'] or not all(isinstance(x,str) and x for x in field['input_variables'])):
            raise ValueError('convection provenance missing')
        if param in ('refl','sigwx'):
            start=parse_utc(field.get('interval_start_utc'))
            end=parse_utc(field.get('interval_end_utc'))
            hours=(end-start).total_seconds()/3600
            if (end!=valid or start<run or hours not in (1,3,6) or field.get('interval_hours')!=hours
                or field.get('clear_value')!=-1 or not field.get('phase_basis')
                or field.get('precipitation_basis')!='native backward sum; raw model rate; not DEM corrected'):
                raise ValueError('weather interval or phase provenance mismatch')
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
    if not valid_coverage(param,field,w,h):
        raise ValueError('insufficient global valid pixels or inconsistent terrain coverage')
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
    catalog={'schema':1,'source':'real model fields through Open-Meteo data_spatial / respective NWP center',
             'license':'Mixed model-specific licences; UKMO forecasts CC BY-SA 4.0; see models.source_license','world_bounds':[-180,-90,180,90],
             'image_base':'world/','models':models,'complete':True,'mock':False}
    dest.mkdir(parents=True,exist_ok=True)
    (dest/'catalog.json').write_text(json.dumps(catalog,ensure_ascii=False,indent=2),encoding='utf8')
    print('WORLD_CATALOG_PUBLISHED',json.dumps({m:list(x['fields']) for m,x in models.items()}),flush=True)
    return catalog

if __name__=='__main__':package(Path(sys.argv[1]),Path(sys.argv[2]))

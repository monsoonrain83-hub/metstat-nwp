#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe منبع برای «بستهٔ شبکه‌ای» (فقط خواندن؛ چیزی ذخیره/آپلود نمی‌شود).
برای هر مدل چک می‌کند کدام متغیرهای موردنیاز سینرژی در Open-Meteo data_spatial هست."""
import json, re, fsspec
DOMS = ['ecmwf_ifs025', 'ecmwf_ifs', 'ncep_gfs025', 'ncep_gfs013', 'dwd_icon', 'ukmo_global_deterministic_10km', 'meteofrance_arpege_world025', 'cmc_gem_gdps']
LEV = [1000, 925, 850, 700, 600, 500, 400, 300, 250, 200, 150, 100]
WANT = {
 'ترازی': [f'{q}_{p}hPa' for q in ('temperature', 'relative_humidity', 'geopotential_height', 'wind_u_component', 'wind_v_component', 'vertical_velocity', 'cloud_cover', 'dew_point', 'specific_humidity') for p in LEV],
 'سطحی': ['surface_pressure', 'pressure_msl', 'temperature_2m', 'dew_point_2m', 'relative_humidity_2m', 'cloud_cover', 'cloud_cover_low', 'cloud_cover_mid', 'cloud_cover_high',
          'cape', 'convective_inhibition', 'lifted_index', 'total_column_integrated_water_vapour', 'wind_u_component_10m', 'wind_v_component_10m', 'freezing_level_height',
          'cloud_water', 'cloud_ice', 'total_cloud_water', 'convective_cloud_cover', 'helicity', 'boundary_layer_height'],
}
fs = fsspec.filesystem('s3', anon=True)
def jget(p):
    try: return json.loads(fs.cat_file(p))
    except Exception: return None
for d in DOMS:
    base = f'openmeteo/data_spatial/{d}'
    j = None
    for f in ('in-progress.json', 'latest.json'):
        j = jget(f'{base}/{f}')
        if j and j.get('variables'): break
    print('=' * 8, d)
    if not j or not j.get('variables'): print('  ✗ latest.json/in-progress.json خوانده نشد'); continue
    vs = set(j['variables']); print(f'  اجرا: {j.get("reference_time")} — {len(vs)} متغیر — {len(j.get("valid_times", []))} گام')
    for g, names in WANT.items():
        have = [n for n in names if n in vs]; miss = [n for n in names if n not in vs]
        if g == 'ترازی':
            for q in ('temperature', 'relative_humidity', 'geopotential_height', 'wind_u_component', 'wind_v_component', 'vertical_velocity', 'cloud_cover', 'dew_point', 'specific_humidity'):
                lv = [p for p in LEV if f'{q}_{p}hPa' in vs]
                print(f'  {q}: ترازها = {lv if lv else "— ندارد"}')
        else:
            print('  سطحی موجود: ' + ', '.join(have)); print('  سطحی ناموجود: ' + ', '.join(miss))
    oth = sorted(v for v in vs if re.search(r'cloud|vertical|omega|helic|water|ice|vort|diverg|thick|wet|wb', v, re.I))
    print('  سایر متغیرهای مرتبط: ' + ', '.join(oth))

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Monthly MetStat independent-source 60/40 multimodel maps.

Inputs: REAL ECMWF SEAS5 ensemble-mean anomalies (CDS) and fresh, individual
NMME monthly anomalies (NOAA CPC). NOAA's precomputed NMME ensemble mean
is expressly excluded. No seasonal multimodel is produced.

Only precipitation and 2m temperature are currently available in the
verified CPC realtime_anom files. 500-hPa monthly products require a real
pressure-level source AND its validated model/hindcast climatology; this
workflow must never fabricate a 500-hPa map or advertise an empty menu item.
"""
import argparse
from datetime import date, datetime, timedelta, timezone
import math
import os
import re
import tempfile

import numpy as np
import extended_mm as X
import lr_maps as L
import nwp_maps as N
import seas5_maps as S
import styles

log = N.log
UTC = timezone.utc
PID_OF = {'t2a': 'lrta', 'tpara': 'lrpa'}
CPC_VAR = {'lrta': 'tmp2m', 'lrpa': 'prate'}
MAX_ISSUE_DIFF_DAYS = 45  # comparing different issuance months beyond this is misleading


def issue_parts(text):
    return datetime.strptime(str(text)[:8], '%Y%m%d').replace(tzinfo=UTC)


def ymk(y, m, offset):
    yy, mm = L.month_add(y, m, int(offset))
    return f'{yy}{mm:02d}'


def load_ecmwf(mock, today):
    """Return (issue YYYYMM0100, {pid: {valid_YYYYMM: 2d field}})."""
    if mock:
        y, m = today.year, today.month
        return f'{y}{m:02d}0100', {
            pid: {ymk(y, m, k): np.full((N.MEH, N.MEW), 1.0 if pid == 'lrta' else 2.0, np.float32)
                  for k in range(6)} for pid in ('lrta', 'lrpa')
        }
    import cdsapi
    c = cdsapi.Client(quiet=True, retry_max=3, sleep_max=30, timeout=1800)
    candidates = [(today.year, today.month)]
    prev = today.replace(day=1) - timedelta(days=1)
    candidates.append((prev.year, prev.month))
    for y, m in candidates:
        products = {}
        for src in ('t2a', 'tpara'):
            with tempfile.TemporaryDirectory() as td:
                filepath = os.path.join(td, src + '.nc')
                try:
                    S.retrieve(c, S.VARS[src][0], y, m, filepath)
                    data, lon, lat, offs, units = S.read_cds(filepath)
                    arr = S.convert(src, data, units)
                    grid = {}
                    for index, off in enumerate(offs):
                        if index >= len(arr): continue
                        f = L.regrid(arr[index], lon, lat)
                        if np.isfinite(f).any(): grid[ymk(y, m, off)] = f
                    if grid: products[PID_OF[src]] = grid
                except Exception as exc:
                    log(f'  ✗ monthly MM SEAS5 {src} {y}-{m:02d}: {type(exc).__name__}: {str(exc)[:180]}')
        if len(products) == len(PID_OF):
            log(f'  ✓ monthly MM ECMWF SEAS5 issue {y}-{m:02d}')
            return f'{y}{m:02d}0100', products
    return None, {}


def list_cpc_issue(model):
    folder = L.MODELS[model][0]
    parent = L.find_dir(folder)
    if parent is None: return None
    names = [s for s in L.links(parent) if re.fullmatch(r'\d{8,10}/', s)]
    if not names: return None
    sub = max(names)
    run = sub[:8] + '00'
    if L.too_old(run, max_days=55):
        log(f'  ⏭ {model}: CPC issuance {run[:8]} is stale'); return None
    return parent + sub, run


def load_cpc(model, ecmwf_issue, mock):
    """Return fields after checking actual issue freshness and exact variable units."""
    if mock:
        if model not in ('cfsv2', 'nasa'): return {}
        y, m = int(ecmwf_issue[:4]), int(ecmwf_issue[4:6])
        v = 2.0 if model == 'cfsv2' else 3.0
        return {pid: {ymk(y, m, k): np.full((N.MEH, N.MEW), v, np.float32) for k in range(6)}
                for pid in ('lrta', 'lrpa')}
    if model not in L.MODELS: return {}
    x = list_cpc_issue(model)
    if x is None: return {}
    path, run = x
    if abs((issue_parts(run) - issue_parts(ecmwf_issue)).days) > MAX_ISSUE_DIFF_DAYS:
        log(f'  ⏭ {model}: issuance not comparable with ECMWF'); return {}
    files = L.links(path)
    products = {}
    y, m = int(run[:4]), int(run[4:6])
    for pid, variable in CPC_VAR.items():
        candidates = [s for s in files if s.lower().endswith('.nc') and variable in s.lower()]
        if not candidates: continue
        try:
            with tempfile.TemporaryDirectory() as td:
                target = os.path.join(td, 'cpc.nc')
                with open(target, 'wb') as handle: handle.write(L.get(path + candidates[0], binary=True))
                a, lon, lat, offs, units = L.read_nc(target, variable)
                unit = re.sub(r'\s+', '', units.lower())
                if pid == 'lrpa':
                    if ('s-1' in unit or 's^-1' in unit or '/s' in unit):
                        multiplier = 86400.0
                    elif 'mm/d' in unit or 'mm/day' in unit:
                        multiplier = 1.0
                    else:
                        raise ValueError(f'unrecognized CPC precipitation rate unit: {units!r}')
                else:
                    if unit not in ('k', 'kelvin', 'degc', '°c', 'c'):
                        raise ValueError(f'unrecognized CPC temperature anomaly unit: {units!r}')
                    multiplier = 1.0  # a delta of 1 K equals a delta of 1 °C
                grid = {}
                for i, off in enumerate(offs[:9]):
                    f = L.regrid(a[i] * multiplier, lon, lat)
                    if np.isfinite(f).any(): grid[ymk(y, m, off)] = f
                if grid: products[pid] = grid
        except Exception as exc:
            log(f'  ✗ {model}/{pid}: {type(exc).__name__}: {str(exc)[:180]}')
    log(f'  ✓ {model} {run} -> {list(products)}')
    return products


def build_maps(fields_by_model):
    """Prepare only real, overlapping valid-month anomalies."""
    out = []
    months = sorted({month for fields in fields_by_model.values() for by_month in fields.values() for month in by_month})
    for month in months:
        for pid in ('lrpa', 'lrta'):
            inputs = {model: fields[pid][month] for model, fields in fields_by_model.items()
                      if pid in fields and month in fields[pid]}
            mix, ws = X.blend('monthly', inputs)
            if mix is None or not np.isfinite(mix).any(): continue
            out.append((pid, month, mix, ws))
    return out


def publish(up, run, maps):
    if not maps: return 0
    active = set(pid for pid, *_ in maps)
    scale_names = {pid: ('lrpa' if pid == 'lrpa' else 'lrta') for pid in active}
    categories = {'lrpa': 'pr', 'lrta': 'tp'}
    title = {'lrpa': 'مولتی‌مدل ماهانه — آنومالی بارش (میلی‌متر در روز)',
             'lrta': 'مولتی‌مدل ماهانه — آنومالی دمای ۲ متری (°C)'}
    payload = {'model': 'mmmo', 'run': run, 'name': 'MetStat MultiModel Monthly',
        'label': 'مولتی‌مدل ماهانه MetStat (ECMWF ۶۰٪ + سایر مدل‌ها ۴۰٪)',
        'info': dict(tclass='monthly', res='multi', cyc='ماهانه', prov='ECMWF SEAS5/CDS; NOAA CPC individual NMME anomalies'),
        'cats': [dict(id=i, fa=fa, o=o) for i, fa, o in N.CATS],
        'scales': {sc: dict(c=styles.SC[sc]['colors'], e=[None if abs(e) == math.inf else e for e in styles.SC[sc]['edges']],
                           lo=True, hi=True) for sc in set(scale_names.values())},
        'params': {pid: dict(fa=title[pid], unit=('°C' if pid == 'lrta' else 'mm/d'), cat=categories[pid], o=90,
                             sc=scale_names[pid], mu=('°C' if pid == 'lrta' else 'mm/d'), alt='', me=1, ln=0)
                   for pid in active}}
    response = up.call('begin', js=payload); already = set(response.get('have', []))
    made = 0
    for pid, month, field, weights in maps:
        valid = f'{month}0100'; fname = f'me/{pid}_{valid}.webp'
        if fname in already: continue
        image, _ = N.render_me(None, field, scale_names[pid])
        wt = ','.join(f'{key}:{round(weight * 100)}' for key, weight in weights.items())
        up.put('mmmo', run, fname, image, dict(r='me', m='mmmo', p=pid, v=valid, w=wt)); made += 1
    up.wait(); up.call('end', js={'model': 'mmmo', 'run': run})
    return made


def main():
    a = argparse.ArgumentParser()
    a.add_argument('--host'); a.add_argument('--key', default='')
    a.add_argument('--out'); a.add_argument('--mock', action='store_true')
    a.add_argument('--force', action='store_true')
    args = a.parse_args()
    if not args.host and not args.out: a.error('--host or --out is required')
    today = date.today()
    # Early and late month stage: refresh after the NOAA forecast around day 8–10.
    run = f'{today.year}{today.month:02d}{10 if today.day >= 10 else 5:02d}00'
    if args.host and not args.force and S.host_run(args.host, 'mmmo') == run:
        log('  ✓ monthly MM already published for this update window'); return 0
    source_run, ecmwf = load_ecmwf(args.mock, today)
    if not ecmwf:
        log('  ✗ no valid ECMWF monthly forecast; refusing non-ECMWF multimodel'); return 0
    fields = {'ecmwfseas': ecmwf}
    for name in X.OTHER['monthly']:
        try:
            product = load_cpc(name, source_run, args.mock)
            if product: fields[name] = product
        except Exception as exc:
            log(f'  ✗ source {name}: {type(exc).__name__}: {str(exc)[:180]}')
    prepared = build_maps(fields)
    if not prepared:
        log('  ✗ no matched ECMWF + independent NMME monthly fields; nothing published'); return 0
    up = N.Uploader(args.host, args.key, args.out)
    count = publish(up, run, prepared)
    log(f'✓ monthly MM {run}: {count} maps, {sorted(fields)} (IRI/NMME ensemble mean excluded)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

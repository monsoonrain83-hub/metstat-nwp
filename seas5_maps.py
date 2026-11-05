#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MetStat r194 — نقشه‌های ماهانه و فصلی ECMWF SEAS5 (C3S، system 51) → کاشی «خاورمیانه» → هاست.
منبع: CDS مجموعه‌داده‌ی seasonal-postprocessed-single-levels، product_type=ensemble_mean (میانگین مجموعه‌ی انومالی نسبت به هم‌پیش‌بینی ۱۹۹۳–۲۰۱۶؛
اقلیم‌گیری را خود ECMWF انجام داده، نیازی به دانلود hindcast نیست). نام متغیرها/ساختار فایل با seas5_probe.py روی CDS واقعی دیده شد
(t2a [K]، tpara [m s-1]؛ بُعدها forecast_reference_time, forecastMonth, latitude, longitude؛ شبکهٔ ۱°).
خروجی روی هاست، مطابق قرارداد lr_maps.py/سایت:
  ecmwfseas  (tclass=monthly)  : ماه k پس از آغاز اجرا؛ نام فایل me/<lrpa|lrta>_<YYYYMM0100>.webp
  ecmwfseass (tclass=seasonal) : میانگین ۳ ماهه؛ v = ماه اول بازه (سایت خودش span=3 را از tclass می‌داند)
فرض‌های آزمون‌نشده: (۱) forecastMonth=1 یعنی ماهِ شروع اجرا (قرارداد CDS) ؛ (۲) درخواست ۶ گام در یک بار به CDS؛ (۳) رندر/آپلود مثل lr_maps.
اجرا: python seas5_maps.py --host https://wtafkik.ir/online --key KEY  |  --mock --out /tmp/o  (آزمون بدون شبکه/CDS)"""
import argparse, datetime as dt, math, os, re, sys, tempfile
import numpy as np
import nwp_maps as N, styles
from lr_maps import regrid, month_add

log = N.log
DS = 'seasonal-postprocessed-single-levels'
AREA = [45, 17, 9, 68]       # N, W, S, E — کادر ME_EXT (۲۰–۶۵°E، ۱۲–۴۲°N) + حاشیه برای درون‌یابی
LEADS = 6
# (نام CDS، شناسه پارامتر سایت، برچسب، واحد، دستهٔ سایت، مقیاس رنگ)
VARS = {'t2a':   ('2m_temperature_anomaly',             'lrta', 'انومالی دمای ۲ متری (°C)',                 '°C',   'tp', 'lrta'),
        'tpara': ('total_precipitation_anomalous_rate', 'lrpa', 'انومالی بارش (میلی‌متر در روز)',            'mm/d', 'pr', 'lrpa')}
SEAS_MODELS = {'ecmwfseas':  dict(tclass='monthly',  span=1, cyc='ماهانه (گام ۱ ماهه)',          fa='ECMWF SEAS5 (ماهانه)'),
               'ecmwfseass': dict(tclass='seasonal', span=3, cyc='فصلی (میانگین ۳ ماهه)',       fa='ECMWF SEAS5 (فصلی)')}

def host_run(host, key):
    """run ثبت‌شده‌ی مدل روی هاست (برای رد کردن اجرای تکراری). خطا → None (یعنی ادامه بده)."""
    if not host: return None
    try:
        import requests
        m = requests.get(host.rstrip('/') + '/data/manifest.json', timeout=60, headers={'User-Agent': 'MetStat-seas5/1.0'}).json()['models']
        return (m.get(key) or {}).get('run')
    except Exception as e:
        log(f'  ⓘ manifest هاست خوانده نشد ({type(e).__name__}) — بدون بررسی تکراری‌بودن ادامه می‌دهم'); return None

def retrieve(c, cds_var, y, m, path):
    c.retrieve(DS, {'originating_centre': 'ecmwf', 'system': '51', 'variable': [cds_var], 'product_type': ['ensemble_mean'], 'year': [str(y)], 'month': [f'{m:02d}'],
                    'leadtime_month': [str(i) for i in range(1, LEADS + 1)], 'area': AREA, 'data_format': 'netcdf'}, path)

def read_cds(path):
    """→ data(lead, lat, lon)، lon، lat، offs (ماه‌های پس از ماه شروع)، units"""
    import xarray as xr, zipfile
    if zipfile.is_zipfile(path):
        d = os.path.dirname(path)
        with zipfile.ZipFile(path) as z: nm = [n for n in z.namelist() if n.endswith(('.nc', '.grib', '.grb'))][0]; z.extract(nm, d); path = os.path.join(d, nm)
    with open(path, 'rb') as f: head = f.read(4)
    ds = xr.open_dataset(path, engine='cfgrib', backend_kwargs={'indexpath': ''}) if head == b'GRIB' else xr.open_dataset(path)
    name = next(iter(ds.data_vars)); v = ds[name]; units = str(v.attrs.get('units', ''))
    for d in list(v.dims):                                   # بُعدهای اضافه (forecast_reference_time، number) → اولی
        if d not in ('forecastMonth', 'latitude', 'longitude'): v = v.isel({d: 0})
    if 'forecastMonth' not in v.dims: v = v.expand_dims('forecastMonth')
    v = v.transpose('forecastMonth', 'latitude', 'longitude')
    offs = [int(x) - 1 for x in np.atleast_1d(v['forecastMonth'].values)]
    return v.values.astype('float64'), np.asarray(v['longitude'].values, float), np.asarray(v['latitude'].values, float), offs, units

def convert(vn, data, units):
    """به واحد نمایش سایت. t2a: انومالی K = °C (بدون تبدیل)؛ tpara: m s-1 (ستون آب) → mm/day."""
    u = units.replace(' ', '').lower()
    if vn == 'tpara':
        if u in ('ms-1', 'ms**-1', 'm/s', 'ms^-1'): return data * 1000.0 * 86400.0
        raise RuntimeError(f'واحد بارش ناشناخته: «{units}» (انتظار m s-1)')
    if u not in ('k', 'kelvin', 'degc', '°c', 'c'): raise RuntimeError(f'واحد دما ناشناخته: «{units}» (انتظار K)')
    return data

def begin_payload(mk, run):
    M = SEAS_MODELS[mk]
    return {'model': mk, 'run': run, 'name': mk.upper(), 'label': M['fa'],
            'info': dict(tclass=M['tclass'], res='1°', cyc=M['cyc'], prov='ECMWF SEAS5 / Copernicus C3S'),
            'cats': [dict(id=i, fa=f, o=o) for i, f, o in N.CATS],
            'scales': {k: dict(c=styles.SC[k]['colors'], e=[None if abs(x) == math.inf else x for x in styles.SC[k]['edges']], lo=True, hi=True) for k in ('lrta', 'lrpa')},
            'params': {v[1]: dict(fa=v[2], unit=v[3], cat=v[4], o=90 + i, sc=v[5], mu=v[3], alt='', me=1, ln=0) for i, v in enumerate(VARS.values())}}

def publish(up, fields, y0, m0, run):
    """fields: {vn: (data_mm(lead,lat,lon) در واحد سایت، lon، lat، offs)} → هر دو مدل (ماهانه + فصلی)"""
    made = {}
    for mk, M in SEAS_MODELS.items():
        started = False; n = 0
        for vn, (arr, lon, lat, offs) in fields.items():
            pid, sc = VARS[vn][1], VARS[vn][5]
            if not started:
                up.call('begin', js=begin_payload(mk, run)); started = True
            for k in range(len(arr) - M['span'] + 1):
                a = arr[k:k + M['span']]
                if offs[k:k + M['span']] != list(range(offs[k], offs[k] + M['span'])): continue            # فقط ماه‌های پیاپی
                f = regrid(np.nanmean(a, axis=0), lon, lat)
                if not np.isfinite(f).any(): continue
                y, m = month_add(y0, m0, offs[k]); valid = f'{y}{m:02d}0100'
                dat, _ = N.render_me(None, f, sc)
                up.put(mk, run, f'me/{pid}_{valid}.webp', dat, dict(s=k)); n += 1
        if started: up.wait(); up.call('end', js={'model': mk, 'run': run}); log(f'✓ {mk} {run}: {n} نقشه'); made[mk] = n
    return made

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--host'); ap.add_argument('--key', default=''); ap.add_argument('--out'); ap.add_argument('--force', action='store_true'); ap.add_argument('--mock', action='store_true')
    a = ap.parse_args(); up = N.Uploader(a.host, a.key, a.out)
    today = dt.date.today(); cand = [(today.year, today.month)]; pm = today.replace(day=1) - dt.timedelta(days=1); cand.append((pm.year, pm.month))
    have = None if a.force else host_run(a.host, 'ecmwfseas'); have2 = None if a.force else host_run(a.host, 'ecmwfseass')
    for (y, m) in cand:
        run = f'{y}{m:02d}0100'
        if have == run and have2 == run: log(f'✓ SEAS5 {run} روی هاست هست؛ کاری لازم نیست'); return 0
        fields = {}
        if a.mock:
            rng = np.random.default_rng(3); la = np.arange(44.5, 8, -1.0); lo = np.arange(17.5, 68)
            for vn in VARS: fields[vn] = (rng.normal(0, 1.0 if vn == 't2a' else 1.0, (LEADS, len(la), len(lo))), lo, la, list(range(LEADS)))
        else:
            import cdsapi
            c = cdsapi.Client(quiet=True, retry_max=3, sleep_max=30, timeout=1800)
            for vn, v in VARS.items():
                with tempfile.TemporaryDirectory() as td:
                    p = os.path.join(td, f'{vn}.nc')
                    try: retrieve(c, v[0], y, m, p)
                    except Exception as e: log(f'  ✗ {vn} {y}-{m:02d}: {type(e).__name__}: {str(e)[:300]}'); break      # این ماه هنوز منتشر نشده → ماه قبل
                    try: d, lon, lat, offs, units = read_cds(p); fields[vn] = (convert(vn, d, units), lon, lat, offs); log(f'  {vn}: shape={d.shape} offs={offs} units="{units}"')
                    except Exception as e: log(f'  ✗ خواندن {vn}: {type(e).__name__}: {e}'); fields = {}; break
        if not fields: continue
        if len(fields) < len(VARS): log('  ⚠ فقط بخشی از پارامترها آمد؛ همان‌ها آپلود می‌شود')
        publish(up, fields, y, m, run); return 0
    log('✗ SEAS5: برای هیچ‌کدام از دو ماه اخیر داده‌ای گرفته نشد'); return 0

if __name__ == '__main__': sys.exit(main())

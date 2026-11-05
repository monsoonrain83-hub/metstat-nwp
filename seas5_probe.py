#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MetStat r194 — آزمون کوچک CDS برای نقشه‌های ماهانه/فصلی ECMWF SEAS5 (system 51) روی ایران و خاورمیانه.
هدف: قبل از نوشتن تولیدکنندهٔ اصلی، نام دقیق مجموعه‌داده/متغیر/product_type و ساختار NetCDF را روی CDS واقعی ببینیم.
هیچ چیزی آپلود نمی‌شود. خروجی: خطوط PROBE برای هر درخواست (موفق یا با پیام خطای CDS).
"""
import datetime as dt, os, sys, tempfile, traceback

AREA = [45, 20, 20, 70]   # N, W, S, E — خاورمیانه/ایران
TESTS = [
    ('A', 'seasonal-postprocessed-single-levels', ['2m_temperature_anomaly'],            'ensemble_mean'),
    ('B', 'seasonal-postprocessed-single-levels', ['total_precipitation_anomalous_rate'], 'ensemble_mean'),
    ('C', 'seasonal-monthly-single-levels',       ['total_precipitation'],                'ensemble_mean'),
]

def summarize(path):
    import xarray as xr, zipfile
    if zipfile.is_zipfile(path):
        d = os.path.dirname(path)
        with zipfile.ZipFile(path) as z:
            nm = [n for n in z.namelist() if n.endswith(('.nc', '.grib', '.grb'))][0]; z.extract(nm, d); path = os.path.join(d, nm)
    with open(path, 'rb') as f: head = f.read(4)
    ds = xr.open_dataset(path, engine='cfgrib', backend_kwargs={'indexpath': ''}) if head == b'GRIB' else xr.open_dataset(path)
    print('  dims :', dict(ds.sizes)); print('  vars :', {k: (v.dims, v.attrs.get('units')) for k, v in ds.data_vars.items()})
    print('  coord:', {k: (str(v.values[:3]) if v.ndim else str(v.values)) for k, v in ds.coords.items()})
    for k, v in ds.data_vars.items():
        a = v.values.astype('float64'); print(f'  {k}: min={a.min():.4g} max={a.max():.4g} nan={int((a != a).sum())}/{a.size}')

def main():
    import cdsapi
    c = cdsapi.Client(quiet=False, retry_max=2, sleep_max=30, timeout=1500)
    today = dt.date.today(); starts = [(today.year, today.month)]
    pm = today.replace(day=1) - dt.timedelta(days=1); starts.append((pm.year, pm.month))   # ماه جاری (اگر منتشر شده) و ماه قبل
    for tag, ds, var, pt in TESTS:
        ok = False
        for (y, m) in starts:
            req = {'originating_centre': 'ecmwf', 'system': '51', 'variable': var, 'product_type': [pt], 'year': [str(y)], 'month': [f'{m:02d}'],
                   'leadtime_month': ['1'], 'area': AREA, 'data_format': 'netcdf'}
            print(f'PROBE {tag} {ds} {var} {pt} شروع={y}-{m:02d}', flush=True)
            f = os.path.join(tempfile.mkdtemp(), f'probe_{tag}.nc')
            try:
                c.retrieve(ds, req, f); print(f'PROBE-OK {tag} {os.path.getsize(f)} bytes'); summarize(f); ok = True; break
            except Exception as e:
                print(f'PROBE-FAIL {tag} {y}-{m:02d}: {type(e).__name__}: {str(e)[:600]}')
        if not ok: print(f'PROBE-RESULT {tag}: ناموفق')
    return 0

if __name__ == '__main__': sys.exit(main())

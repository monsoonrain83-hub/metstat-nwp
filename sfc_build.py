#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MetStat r82 — داده‌های «پیش‌بینی ماهانه و فصلی» (هستهٔ تحلیل اقلیم)؛ اجرا روز ۱ و ۱۵ هر ماه میلادی (sfc.yml).
خروجی در پوشهٔ --out (با FTPS به online/data/sfc/ می‌رود):
  sfc_idx.json   : سری ماهانهٔ تازهٔ شاخص‌ها از ۱۹۵۰ (NOAA PSL و CPC؛ MJO از OMI در صورت وجود mjo_index.py) + تاریخ صدور.
  era5_iran.json : بارش (mm/ماه) و دمای ۲ متری (°C) ماهانهٔ ERA5 روی شبکهٔ ۰٫۵° داخل ایران از ۱۹۵۰ (Copernicus CDS؛ نیاز به CDSAPI_KEY).
                   اگر کلید نباشد یا --no-era5، فقط شاخص‌ها ساخته می‌شوند (سایت با دادهٔ اطلس کار می‌کند).
پیش‌بینی شاخص‌ها و نقشه‌ها در خود سایت (67_seasonal_fc.js) با همین داده ساخته می‌شود؛ پس همهٔ کاربران نتیجهٔ یکسان می‌بینند.
اجرا:  python sfc_build.py --out sfc_out [--no-era5]      |   python sfc_build.py --out sfc_out --mock  (آزمون بدون شبکه)"""
import argparse, base64, datetime as dt, io, json, math, os, sys, zipfile
import numpy as np

PSL = 'https://psl.noaa.gov/data/correlation/'
CPC_TELE = 'https://ftp.cpc.ncep.noaa.gov/wd52dg/data/indices/tele_index.nh'
# کلید = نام همان شاخص در اطلس سایت؛ مقدار = فهرست منبع‌ها به ترتیب اولویت ('psl' جدول سال+۱۲ ماه، 'tele' ستون جدول CPC، 'cpc12' جدول سال+۱۲ CPC)
SRC = {
 'NINO 3/4': [('psl', PSL + 'nina34.anom.data')],
 'nino 3':   [('psl', PSL + 'nina3.anom.data')],
 'Nino 4':   [('psl', PSL + 'nina4.anom.data')],
 'nino 1':   [('psl', PSL + 'nina1.anom.data')],
 'ONI':      [('psl', PSL + 'oni.data')],
 'MEI v2':   [('psl', 'https://psl.noaa.gov/enso/mei/data/meiv2.data')],
 'SOI':      [('psl', PSL + 'soi.data')],
 'DMI':      [('psl', 'https://psl.noaa.gov/gcos_wgsp/Timeseries/Data/dmi.had.long.data'), ('psl', PSL + 'dmi.data')],
 'QBO30':    [('psl', PSL + 'qbo.data')],
 'QBO50':    [('cpc12', 'https://www.cpc.ncep.noaa.gov/data/indices/qbo.u50.index')],
 'PDO':      [('psl', PSL + 'pdo.data'), ('psl', 'https://www.ncei.noaa.gov/pub/data/cmb/ersst/v5/index/ersst.v5.pdo.dat')],
 'AMO':      [('psl', PSL + 'amon.us.data')],
 'TNA':      [('psl', PSL + 'tna.data')],
 'AO':       [('psl', PSL + 'ao.data')],
 'AAO':      [('psl', PSL + 'aao.data')],
 'EPO':      [('psl', PSL + 'epo.data')],
 'NAO':      [('tele', 'NAO'), ('psl', PSL + 'nao.data')],
 'EA':       [('tele', 'EA'), ('psl', PSL + 'ea.data')],
 'WP':       [('tele', 'WP'), ('psl', PSL + 'wp.data')],
 'ep/np':    [('tele', 'EP/NP')],
 'PNA':      [('tele', 'PNA'), ('psl', PSL + 'pna.data')],
 'EAWR':     [('tele', 'EA/WR')],
 'SCAND':    [('tele', 'SCA'), ('psl', PSL + 'scand.data')],
 'POL':      [('tele', 'POL')],
}
G0 = (1950, 1)
IRAN = [[52.13, 27.76], [51.4, 27.93], [51.02, 28.82], [50.81, 28.92], [50.92, 29.07], [50.67, 29.11], [50.66, 29.43], [50.14, 29.93], [50.06, 30.2], [49.55, 30.0], [49.47, 30.16], [49.23, 30.14], [49.28, 30.46], [48.89, 30.51], [49.06, 30.43], [48.85, 30.32], [48.93, 30.03], [48.58, 29.9], [48.46, 30.0], [48.4, 30.21], [48.04, 30.48], [48.03, 30.99], [47.7, 30.99], [47.7, 31.4], [47.86, 31.79], [47.45, 32.4], [47.11, 32.48], [46.41, 32.94], [46.1, 32.97], [46.17, 33.06], [46.05, 33.12], [46.2, 33.25], [45.41, 33.97], [45.58, 34.14], [45.45, 34.44], [45.54, 34.59], [45.75, 34.54], [45.7, 34.81], [45.93, 35.08], [46.19, 35.11], [46.01, 35.68], [46.35, 35.81], [45.76, 35.8], [45.56, 36.0], [45.36, 35.98], [45.28, 36.39], [45.1, 36.43], [45.05, 36.73], [44.86, 36.79], [44.92, 37.02], [44.78, 37.11], [44.82, 37.31], [44.6, 37.44], [44.63, 37.73], [44.24, 37.89], [44.51, 38.33], [44.32, 38.38], [44.32, 38.83], [44.05, 39.38], [44.42, 39.41], [44.49, 39.69], [44.63, 39.78], [45.44, 38.99], [46.18, 38.83], [46.53, 38.87], [47.38, 39.46], [47.99, 39.7], [48.38, 39.37], [48.13, 39.24], [48.36, 39.0], [48.02, 38.84], [48.69, 38.4], [48.88, 38.44], [48.93, 37.9], [49.22, 37.56], [50.19, 37.39], [50.48, 37.02], [51.67, 36.6], [54.02, 36.95], [53.58, 36.81], [54.02, 36.81], [53.9, 37.34], [54.68, 37.44], [54.86, 37.76], [55.47, 38.08], [56.34, 38.07], [56.42, 38.24], [56.76, 38.27], [57.04, 38.17], [57.23, 38.27], [57.36, 37.97], [58.16, 37.79], [58.39, 37.62], [58.82, 37.69], [59.35, 37.52], [59.55, 37.12], [60.02, 37.03], [60.37, 36.62], [61.15, 36.66], [61.19, 36.55], [61.23, 36.15], [61.12, 35.97], [61.25, 35.89], [61.28, 35.54], [61.09, 35.26], [60.99, 34.63], [60.73, 34.52], [60.94, 34.31], [60.69, 34.31], [60.51, 34.08], [60.53, 33.65], [60.95, 33.51], [60.64, 33.23], [60.59, 33.03], [60.88, 32.2], [60.83, 31.51], [61.71, 31.38], [61.84, 31.04], [61.8, 30.83], [60.87, 29.85], [61.37, 29.35], [61.8, 28.64], [62.59, 28.25], [62.79, 28.28], [62.78, 27.23], [63.32, 27.14], [63.17, 26.65], [62.44, 26.57], [62.28, 26.36], [61.85, 26.23], [61.66, 25.3], [61.42, 25.06], [60.61, 25.29], [60.54, 25.44], [60.41, 25.38], [60.47, 25.29], [59.45, 25.47], [59.09, 25.4], [58.79, 25.57], [58.12, 25.56], [57.95, 25.7], [57.76, 25.64], [57.7, 25.76], [57.31, 25.79], [57.06, 26.37], [56.97, 27.02], [56.66, 27.18], [56.12, 27.15], [55.64, 26.98], [55.47, 26.75], [55.25, 26.78], [54.62, 26.5], [54.29, 26.73], [53.73, 26.7], [53.46, 26.98], [52.83, 27.2], [52.58, 27.38], [52.67, 27.46], [52.49, 27.61], [52.13, 27.76]]
def log(*a): print(*a, flush=True)
def http(url):
    import requests
    r = requests.get(url, timeout=90, headers={'User-Agent': 'MetStat-sfc/1.0'}); r.raise_for_status(); return r.text
def months_until(today):
    return (today.year - G0[0]) * 12 + today.month - G0[1] + 1
def parse_y12(text, n):
    """جدول «سال + ۱۲ ماه» (PSL/NCEI/CPC). فقط اولین جدول هر سال؛ مقدارهای گمشده (−99.9 و …) → None."""
    out = [None] * n; seen = set()
    for ln in text.splitlines():
        p = ln.replace(',', ' ').split()
        if len(p) < 13 or not p[0].isdigit(): continue
        y = int(p[0])
        if not 1850 <= y <= 2100 or y in seen: continue
        try: row = [float(x) for x in p[1:13]]
        except ValueError: continue
        seen.add(y)
        for m, x in enumerate(row):
            i = (y - G0[0]) * 12 + m
            if 0 <= i < n and abs(x) < 90 and round(x, 2) not in (-9.99, -99.9, -99.99, 99.99): out[i] = x
    return out
def parse_tele(text, col, n):
    """CPC tele_index.nh: «yyyy mm NAO EA WP EP/NP PNA EA/WR SCA TNH POL PT Expl.Var»"""
    hdr = None; out = [None] * n
    for ln in text.splitlines():
        p = ln.split()
        if not p: continue
        if hdr is None and 'NAO' in p and 'PNA' in p: hdr = [h for h in p if h not in ('yyyy', 'mm')]; continue
        if hdr is None or len(p) < 3 or not p[0].isdigit(): continue
        y, m = int(p[0]), int(p[1]); vals = p[2:]
        if col not in hdr or hdr.index(col) >= len(vals): continue
        try: x = float(vals[hdr.index(col)])
        except ValueError: continue
        i = (y - G0[0]) * 12 + m - 1
        if 0 <= i < n and x > -90: out[i] = x
    return out
def last_ok(a):
    for i in range(len(a) - 1, -1, -1):
        if a[i] is not None: return i
    return -1
def build_indices(today, mock=False):
    n = months_until(today); V = {}; used = {}; tele = None
    rng = np.random.default_rng(1)
    for k, srcs in SRC.items():
        if mock:
            x = np.zeros(n); e = rng.normal(0, 1, n)
            for i in range(1, n): x[i] = 0.85 * x[i - 1] + 0.5 * e[i]
            if k.startswith('QBO'): x = 15 * np.sin(2 * np.pi * np.arange(n) / 28 + (0.8 if k == 'QBO50' else 0)) + rng.normal(0, 2, n)
            V[k] = [round(float(v), 3) for v in x[:-2]] + [None, None]; used[k] = 'mock'; continue
        for kind, u in srcs:
            try:
                if kind == 'tele':
                    if tele is None: tele = http(CPC_TELE)
                    a = parse_tele(tele, u, n); src = CPC_TELE + ' [' + u + ']'
                else:
                    a = parse_y12(http(u), n); src = u
                if last_ok(a) < n - 36: log(f'  ؟ {k}: {u} قدیمی است'); continue
                V[k] = [None if v is None else round(v, 3) for v in a]; used[k] = src; break
            except Exception as e: log(f'  ✗ {k} از {u}: {e}')
        if k in V: li = last_ok(V[k]); log(f'✓ {k}: آخرین ماه {G0[0] + li // 12}-{li % 12 + 1:02d}')
        else: log(f'✗ {k}: هیچ منبعی جواب نداد')
    # MJO (OMI، همان روش mjo_index.py)
    try:
        import mjo_index as MJ
        days = {}
        try: days.update(MJ.parse(MJ.get(MJ.URL0), 'orig'))
        except Exception as e: log('  ! OMI orig:', e)
        days.update(MJ.parse(MJ.get(MJ.URL), 'new'))
        J = MJ.build(days); off = (J['g0'][0] - G0[0]) * 12 + J['g0'][1] - G0[1]
        for k, a in J['v'].items():
            o = [None] * n
            for i, v in enumerate(a):
                if 0 <= i + off < n: o[i + off] = v
            V[k] = o; used[k] = 'NOAA PSL OMI'
        log('✓ MJO:', J.get('last'))
    except Exception as e: log('  ؟ MJO اضافه نشد:', e)
    return {'ver': 1, 'issued': dt.datetime.utcnow().replace(microsecond=0).isoformat() + 'Z', 'g0': list(G0), 'n': n, 'src': used, 'v': V}

# ───────── ERA5 ماهانه (CDS) ─────────
def in_ring(lon, lat, ring):
    c = False; j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]; xj, yj = ring[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi: c = not c
        j = i
    return c
def iran_mask(lats, lons):
    """نقطه‌های داخل ایران یا در فاصلهٔ ۰٫۲۵° از مرز (برای پوشش نوار مرزی)."""
    keep = []
    for i, la in enumerate(lats):
        for j, lo in enumerate(lons):
            if any(in_ring(lo + dx, la + dy, IRAN) for dx in (-0.25, 0, 0.25) for dy in (-0.25, 0, 0.25)): keep.append((i, j))
    return keep
def b64i16(a):
    return base64.b64encode(np.ascontiguousarray(a, dtype='<i2').tobytes()).decode()
def era5(today, workdir, mock=False):
    lats = np.arange(40.0, 24.99, -0.5); lons = np.arange(44.0, 63.51, 0.5)
    n = months_until(today) - 1                                    # ERA5 ماهانه تا ماه قبل
    if mock:
        rng = np.random.default_rng(3); LA, LO = np.meshgrid(lats, lons, indexing='ij'); t = np.arange(n)
        clim = np.clip(60 - (LO - 44) * 2.5 + (LA - 30) * 3, 3, None)[None] * (1 + np.cos(2 * np.pi * (t[:, None, None] % 12 - 1) / 12)) / 2
        tp = np.maximum(0, clim * rng.gamma(2, 0.5, (n,) + LA.shape)); t2 = 18 + 12 * np.sin(2 * np.pi * (t[:, None, None] % 12 - 3) / 12) - (LA[None] - 30) * 0.6 + rng.normal(0, 1, (n,) + LA.shape)
    else:
        import cdsapi, xarray as xr
        c = cdsapi.Client(quiet=True, retry_max=3, sleep_max=30, timeout=600)
        years = [str(y) for y in range(G0[0], today.year + 1)]
        target = os.path.join(workdir, 'era5_month.dl')
        c.retrieve('reanalysis-era5-single-levels-monthly-means', {
            'product_type': ['monthly_averaged_reanalysis'], 'variable': ['total_precipitation', '2m_temperature'],
            'year': years, 'month': [f'{m:02d}' for m in range(1, 13)], 'time': ['00:00'],
            'area': [40, 44, 25, 63.5], 'grid': [0.5, 0.5], 'data_format': 'netcdf', 'download_format': 'unarchived'}, target)
        files = []
        if zipfile.is_zipfile(target):
            with zipfile.ZipFile(target) as z:
                for nm in z.namelist():
                    if nm.endswith('.nc'): p = os.path.join(workdir, os.path.basename(nm)); open(p, 'wb').write(z.read(nm)); files.append(p)
        else: files = [target]
        ds = xr.merge([xr.open_dataset(f) for f in files], compat='override')
        tn = 'valid_time' if 'valid_time' in ds.dims else 'time'
        ds = ds.sortby('latitude', ascending=False).sortby('longitude')
        ds = ds.reindex(latitude=lats, longitude=lons, method='nearest', tolerance=0.01)
        tt = ds[tn].values.astype('datetime64[M]').astype(int)              # ماه از ۱۹۷۰
        idx = (tt + 1970 * 12) - (G0[0] * 12 + G0[1] - 1)
        n = int(idx.max()) + 1
        days = np.array([((np.datetime64(f'{G0[0] + i // 12}-{i % 12 + 1:02d}', 'M') + 1).astype('datetime64[D]') - np.datetime64(f'{G0[0] + i // 12}-{i % 12 + 1:02d}', 'M').astype('datetime64[D]')).astype(int) for i in range(n)])
        tp = np.full((n, len(lats), len(lons)), np.nan, np.float32); t2 = tp.copy()
        tpv = ds['tp'].values; t2v = ds['t2m'].values
        for k, i in enumerate(idx):
            if 0 <= i < n: tp[i] = tpv[k] * 1000.0 * days[i]; t2[i] = t2v[k] - 273.15        # m/day → mm/ماه؛ K → °C
    keep = iran_mask(lats, lons)
    P = np.full((len(keep), n), -32768, np.int16); T = P.copy()
    for q, (i, j) in enumerate(keep):
        a = tp[:, i, j]; b = t2[:, i, j]
        P[q] = np.where(np.isfinite(a), np.clip(np.round(a * 10), -32767, 32767), -32768)
        T[q] = np.where(np.isfinite(b), np.round(b * 100), -32768)
    log(f'✓ ERA5: {len(keep)} نقطه × {n} ماه')
    return {'v': 1, 'built': today.isoformat(), 'g0': list(G0), 'nm': n, 'pts': [[float(lats[i]), float(lons[j])] for i, j in keep], 'pr': b64i16(P), 't2': b64i16(T),
            'src': 'ERA5 monthly averaged reanalysis (Copernicus CDS, CC BY 4.0); 0.5°'}

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--out', default='sfc_out'); ap.add_argument('--mock', action='store_true'); ap.add_argument('--no-era5', action='store_true'); ap.add_argument('--no-seas5', action='store_true')
    a = ap.parse_args(); os.makedirs(a.out, exist_ok=True); today = dt.date.today()
    J = build_indices(today, a.mock)
    if len(J['v']) < 8 and not a.mock: sys.exit('✗ شاخص‌های کافی دریافت نشد')
    if a.mock or (os.environ.get('CDSAPI_KEY') and not a.no_seas5):
        try:
            import seas5
            V = {k: v for k, v in J['v'].items()}
            for (yy, mm) in [(today.year, today.month), (today.year - (today.month == 1), (today.month - 2) % 12 + 1)]:
                try: fc = seas5.build(V, G0, mm, yy, a.out, a.mock)
                except Exception as e: log(f'  ✗ SEAS5 {yy}-{mm:02d}:', e); continue
                if fc and fc.get('n', 0) > 0: J['fc'] = fc; log(f'✓ پیش‌بینی SEAS5 از {yy}-{mm:02d}: شاخص‌ها {list(fc["z"])}'); break
        except Exception as e: log('  ✗ SEAS5:', e)
    json.dump(J, open(os.path.join(a.out, 'sfc_idx.json'), 'w'), separators=(',', ':')); log(f'sfc_idx.json: {len(J["v"])} شاخص')
    if a.no_era5 or (not a.mock and not os.environ.get('CDSAPI_KEY')): log('ERA5 ساخته نشد (کلید CDSAPI_KEY نیست یا --no-era5)'); return
    try:
        E = era5(today, a.out, a.mock)
        json.dump(E, open(os.path.join(a.out, 'era5_iran.json'), 'w'), separators=(',', ':')); log('era5_iran.json:', os.path.getsize(os.path.join(a.out, 'era5_iran.json')) // 1024, 'KB')
    except Exception as e: log('✗ ERA5:', e)
    for f in os.listdir(a.out):
        if not f.endswith('.json'): os.remove(os.path.join(a.out, f))

if __name__ == '__main__': main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MetStat r82 — پیش‌بینی شاخص‌ها از خروجی ECMWF SEAS5 (Copernicus CDS)، برای sfc_build.py
هر عضو مجموعه: شاخص از میدان‌های پیش‌بینی‌شده محاسبه می‌شود (نه از میانگین مجموعه)، سپس با هم‌پیش‌بینی‌های ۱۹۹۳–۲۰۱۶ همان مدل
به z-score تبدیل می‌شود (اریبی‌زدایی)؛ شیب و مهارت هر ماه‌پیش‌بینی با همبستگی هم‌پیش‌بینی و مشاهده (سری‌های PSL/CPC) سنجیده می‌شود.
شاخص‌ها: NINO 3/4 (SST)، DMI (SST)، NAO (فشار تراز دریا: آزور − ایسلند)، AO (نمایه: −میانگین فشار >۶۵°N)، PNA (ارتفاع ۵۰۰ hPa، فرمول ۴ مرکز).
QBO/PDO/MJO/EA-WR/SCAND و … پیش‌بینی مدلی ندارند و در سایت با رگرسیون تاریخچه برآورد می‌شوند.
⚠ نام بُعدها و متغیرهای NetCDF خروجی CDS با نسخهٔ API تغییر می‌کند؛ کد با نام‌های رایج دفاعی نوشته شده ولی روی CDS واقعی آزمون نشده است.
"""
import datetime as dt, os
import numpy as np

HC_Y = list(range(1993, 2017)); LEADS = 6
# جعبه‌ها (lat0, lat1, lon0, lon1) با طول شرقی ۰–۳۶۰
BOX = {'n34': (-5, 5, 190, 240), 'wtio': (-10, 10, 50, 70), 'setio': (-10, 0, 90, 110), 'azo': (30, 40, 320, 340), 'ice': (60, 70, 330, 350), 'arc': (65, 90, 0, 360)}
PNA_PTS = [(20, 200, +1), (45, 195, -1), (55, 245, +1), (30, 275, -1)]          # 20N160W, 45N165W, 55N115W, 30N85W
REQ = {   # نام گروه: (متغیر CDS، نام متغیر در فایل، سطح، area[N,W,S,E])
 'pac': ('sea_surface_temperature', ['sst'], None, [6, -175, -6, -115]),
 'ind': ('sea_surface_temperature', ['sst'], None, [12, 45, -12, 112]),
 'atl': ('mean_sea_level_pressure', ['msl'], None, [72, -45, 28, -8]),
 'arc': ('mean_sea_level_pressure', ['msl'], None, [90, -180, 65, 180]),
 'pna': ('geopotential', ['z'], '500', [60, -170, 15, -80]),
}
def log(*a): print(*a, flush=True)

def retrieve(c, grp, years, month, workdir):
    var, _, lev, area = REQ[grp]; ds = 'seasonal-monthly-pressure-levels' if lev else 'seasonal-monthly-single-levels'
    r = {'originating_centre': 'ecmwf', 'system': '51', 'variable': [var], 'product_type': ['monthly_mean'], 'year': [str(y) for y in years],
         'month': [f'{month:02d}'], 'leadtime_month': [str(i) for i in range(1, LEADS + 1)], 'area': area, 'data_format': 'netcdf'}      # download_format برای این مجموعه‌دادهٔ فصلی پشتیبانی نمی‌شود (هشدار CDS)
    if lev: r['pressure_level'] = [lev]
    f = os.path.join(workdir, f's5_{grp}_{years[0]}_{month}.nc'); c.retrieve(ds, r, f); return f

def open_any(path):
    """CDS گاهی بدون توجه به data_format فایل را «as_source» (GRIB) یا zip می‌دهد؛ هر سه را می‌خوانیم."""
    import xarray as xr, zipfile
    if zipfile.is_zipfile(path):
        d = os.path.dirname(path) or '.'
        with zipfile.ZipFile(path) as z: nm = [n for n in z.namelist() if n.endswith(('.nc', '.grib', '.grb'))][0]; z.extract(nm, d); path = os.path.join(d, nm)
    with open(path, 'rb') as f: head = f.read(4)
    if head == b'GRIB':
        return xr.open_dataset(path, engine='cfgrib', backend_kwargs={'indexpath': ''})
    return xr.open_dataset(path)

def tidy(path, names):
    """→ DataArray (year, member, lead, lat, lon) ؛ lon به ۰–۳۶۰."""
    import xarray as xr
    d = open_any(path); v = next((n for n in names if n in d), None) or list(d.data_vars)[0]; a = d[v]
    dm = {x: None for x in a.dims}
    t = next((x for x in ('forecast_reference_time', 'time', 'start_date') if x in a.dims), None)
    lead = next((x for x in ('forecastMonth', 'step', 'leadtime_month', 'forecast_period') if x in a.dims), None)
    num = next((x for x in ('number', 'member', 'ensemble') if x in a.dims), None)
    if lead: a = a.sortby(lead)
    la = next(x for x in ('latitude', 'lat') if x in a.dims); lo = next(x for x in ('longitude', 'lon') if x in a.dims)
    for extra in [x for x in a.dims if x in ('pressure_level', 'level', 'isobaricInhPa')]: a = a.isel({extra: 0}, drop=True)     # تراز تکی (۵۰۰ hPa) را حذف می‌کنیم
    if num is None: a = a.expand_dims('number'); num = 'number'
    yrs = a[t].dt.year.values if t else np.array([0])
    a = a.assign_coords(**{lo: (a[lo] % 360)}) if True else a
    return a, t, lead, num, la, lo, yrs

def boxmean(a, la, lo, box):
    la0, la1, lo0, lo1 = box
    s = a.sel({la: slice(*sorted((la0, la1)))}) if a[la][0] < a[la][-1] else a.sel({la: slice(la1, la0)})
    m = (s[lo] >= lo0) & (s[lo] <= lo1); s = s.where(m, drop=True)
    w = np.cos(np.deg2rad(s[la])); return s.weighted(w).mean([la, lo])

def series(grp, path):
    """→ dict شاخص خام: {name: array(year, member, lead)} و فهرست سال‌ها"""
    a, t, lead, num, la, lo, yrs = tidy(path, REQ[grp][1]); out = {}
    def arr(x): return x.transpose(*( [t] if t else [] ), num, lead).values.reshape(len(yrs), -1, LEADS)
    if grp == 'pac': out['NINO 3/4'] = arr(boxmean(a, la, lo, BOX['n34']))
    if grp == 'ind': out['DMI'] = arr(boxmean(a, la, lo, BOX['wtio'])) - arr(boxmean(a, la, lo, BOX['setio']))
    if grp == 'atl': out['NAO'] = arr(boxmean(a, la, lo, BOX['azo'])) - arr(boxmean(a, la, lo, BOX['ice']))
    if grp == 'arc': out['AO'] = -arr(boxmean(a, la, lo, BOX['arc']))
    if grp == 'pna':
        z = 0
        for lat, lon, sg in PNA_PTS: z = z + sg * arr(a.sel({la: lat, lo: lon}, method='nearest'))
        out['PNA'] = z / 4.0
    return out, yrs

def build(V, g0, month, year, workdir, mock=False):
    """V: سری‌های مشاهده‌ای PSL (فهرست ماهانه از g0)؛ month/year: ماه آغاز پیش‌بینی (روز ۱ آن ماه صادر شده)."""
    raw_h, raw_f = {}, {}
    if mock:
        rng = np.random.default_rng(5)
        for k in ('NINO 3/4', 'DMI', 'NAO', 'AO', 'PNA'):
            ob = lambda y, l: V[k][(y - g0[0]) * 12 + (month - 1 + l) - (g0[1] - 1)] if k in V else None
            h = np.zeros((len(HC_Y), 25, LEADS)); f = np.zeros((1, 51, LEADS))
            for i, y in enumerate(HC_Y):
                for l in range(LEADS):
                    o = ob(y, l); o = 0 if o is None else o; h[i, :, l] = 0.6 * o * (0.9 ** l) + rng.normal(0, 0.5 + 0.1 * l, 25)
            for l in range(LEADS): f[0, :, l] = 0.5 * (0.9 ** l) + rng.normal(0, 0.5 + 0.1 * l, 51)
            raw_h[k] = h; raw_f[k] = f
    else:
        import cdsapi
        c = cdsapi.Client(quiet=True, retry_max=3, sleep_max=30, timeout=1800)
        for grp in REQ:
            try:
                h, _ = series(grp, retrieve(c, grp, HC_Y, month, workdir)); f, fy = series(grp, retrieve(c, grp, [year], month, workdir))
                for k in h:
                    hh = h[k]; ff = f[k]
                    if hh.shape[1] < 51: hh = np.concatenate([hh, np.full((hh.shape[0], 51 - hh.shape[1], LEADS), np.nan)], 1)
                    raw_h[k] = hh[:, :hh.shape[1]]; raw_f[k] = ff; log(f'  ✓ SEAS5 {k}: همپیش‌بینی {h[k].shape}، پیش‌بینی {ff.shape}')
            except Exception as e: log(f'  ✗ SEAS5 {grp}: {e}')
    z, skill, slope = {}, {}, {}
    for k in raw_h:
        h = raw_h[k]; f = raw_f[k]
        mu = np.nanmean(h, axis=(0, 1)); sd = np.nanstd(h, axis=(0, 1)) + 1e-9           # اقلیم مدل برای هر ماه‌پیش‌بینی
        zh = (h - mu) / sd; zf = (f - mu) / sd
        zm = np.nanmean(zf[0], axis=0); z[k] = [[round(float(x), 3) for x in zf[0][i]] for i in range(zf.shape[1])]
        sk, sl = [], []
        for l in range(LEADS):
            if k not in V: sk.append(0); sl.append(0); continue
            gi = [(y - g0[0]) * 12 + (month - 1 + l) - (g0[1] - 1) for y in HC_Y]
            ob = np.array([V[k][i] if 0 <= i < len(V[k]) and V[k][i] is not None else np.nan for i in gi], float)
            ob = (ob - np.nanmean(ob)) / (np.nanstd(ob) + 1e-9); em = np.nanmean(zh[:, :, l], axis=1); ok = np.isfinite(ob) & np.isfinite(em)
            if ok.sum() < 10: sk.append(0); sl.append(0); continue
            r = float(np.corrcoef(em[ok], ob[ok])[0, 1]); b = float(np.sum(em[ok] * ob[ok]) / np.sum(em[ok] ** 2)); sk.append(round(r, 3)); sl.append(round(b, 3))
        skill[k] = sk; slope[k] = sl
        log(f'  {k}: مهارت هم‌پیش‌بینی r = {sk}')
    return {'start': [year, month], 'leads': LEADS, 'n': (len(next(iter(z.values()))) if z else 0), 'z': z, 'skill': skill, 'slope': slope,
            'src': 'ECMWF SEAS5 (C3S/CDS)؛ هم‌پیش‌بینی ۱۹۹۳–۲۰۱۶', 'mock': bool(mock)}

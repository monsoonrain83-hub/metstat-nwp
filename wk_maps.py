#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MetStat r81 — نقشه‌های هفتگی و فصلی تازه برای بخش «مدل‌های هفتگی/فصلی» صفحهٔ اول:

 ۱) ECMWF EC46 — انومالی هفتگی دمای ۲ متری و بارش (هفته‌های ۱ تا ۶) از Open-Meteo Seasonal API (weekly=…_anomaly)؛
    انومالی نسبت به «اقلیم خود مدل» (hindcast چندساله) — روش استاندارد ECMWF. اگر API انومالی هفتگی ندهد، این مدل ساخته نمی‌شود.
 ۲) CFSv2 — انومالی هفتگی (هفته‌های ۱ تا ۵) از میانگین ۴ عضو CFS (همان دادهٔ ens_maps: s3://noaa-cfs-pds) منهای اقلیم ماهانهٔ
    ۱۹۹۱–۲۰۲۰ بازتحلیل NCEP/NCAR (PSL)، درون‌یابی‌شده به میانهٔ هر هفته. اریبی خود مدل حذف نمی‌شود (CPC از اقلیم بازپیش‌بینی CFS استفاده می‌کند).
 ۳) IRI (دانشگاه کلمبیا) — پیش‌بینی احتمالاتی فصلی سه‌دهکی (tercile) بارش و دما، ۴ فصل پیش‌رو، از کتابخانهٔ دادهٔ IRI
    (NMME_Seasonal_Forecast …_ELR/.prob). نقشه = دهک غالب و احتمال آن (رنگ‌بندی استاندارد IRI؛ خاکستری = نرمال غالب، سفید = بدون برتری).
    محصولات هفتگی و ماهانهٔ IRI: مسیر دادهٔ آن‌ها از اینجا قابل تأیید نبود؛ با متغیر IRI_SUBX_PATH قابل افزودن است (هنوز ساخته نمی‌شود).

اجرا:  python wk_maps.py --host https://wtafkik.ir/online --key KEY [--only ecwk,cfswk,iri]   |   --out DIR --mock (آزمون بدون شبکه)
"""
import argparse, io, math, os, sys, time
from datetime import datetime, timedelta, timezone
import numpy as np
import nwp_maps as N, styles, lr_maps as L

UTC = timezone.utc; log = N.log
CROP = (16.0, 69.0, 8.0, 46.0)
INF = math.inf
# ---------------------------------------------------------------- رنگ‌بندی‌ها (گسسته)
styles.SC.setdefault('wkta', dict(colors=styles._P['wu_tanom'], edges=[-INF, -6, -5, -4, -3, -2.5, -2, -1.5, -1, -0.5, -0.25, 0.25, 0.5, 1, 1.5, 2, 2.5, 3, 4, 5, 6, INF]))
styles.SC.setdefault('wkpa', dict(colors=['#543005', '#7f4a0c', '#a3691a', '#bf8a2e', '#d6aa55', '#e6c88a', '#f0dcb3', '#f7ecd3', '#ffffff', '#d9efe8', '#b3e0d3', '#86cdbc', '#55b4a3', '#2f9a8c', '#1a7e75', '#0b6159', '#00443f'],
                                  edges=[-INF, -40, -30, -20, -15, -10, -6, -3, -1, 1, 3, 6, 10, 15, 20, 30, 40, INF]))
# سه‌دهکی IRI: مقدار = −احتمال (پایین‌تر از نرمال)، +احتمال (بالاتر)، ۰ (نرمال غالب)؛ کمتر از ۴۰٪ = بدون برتری (سفید)
_TER_P = ['#7f3b08', '#b35806', '#e08214', '#fdb863', '#fee0b6', '#ffffff', '#bdbdbd', '#ffffff', '#c7e9c0', '#74c476', '#31a354', '#006d2c', '#00441b']
_TER_T = ['#08306b', '#2171b5', '#4292c6', '#9ecae1', '#deebf7', '#ffffff', '#bdbdbd', '#ffffff', '#fee0d2', '#fc9272', '#ef3b2c', '#cb181d', '#67000d']
_TER_E = [-INF, -70, -60, -50, -45, -40, -0.5, 0.5, 40, 45, 50, 60, 70, INF]
styles.SC.setdefault('terp', dict(colors=_TER_P, edges=_TER_E)); styles.SC.setdefault('tert', dict(colors=_TER_T, edges=_TER_E))
for _k in ('wkta', 'wkpa', 'terp', 'tert'): assert len(styles.SC[_k]['edges']) == len(styles.SC[_k]['colors']) + 1, _k

MODELS = {
    'ecwk':  dict(label='ECMWF EC46 — انومالی هفتگی (۶ هفته)', name='ECMWF-EC46-WEEKLY', res='نقطه‌ای ۱٫۵°', cyc='روزانه', prov='ECMWF EC46 · Open-Meteo Seasonal API (CC BY 4.0); انومالی نسبت به اقلیم مدل', tclass='weekly'),
    'cfswk': dict(label='CFSv2 — انومالی هفتگی (۵ هفته، میانگین ۴ عضو)', name='CFSv2-WEEKLY', res='~0.5°', cyc='روزانه', prov='NOAA CFSv2 (AWS) · اقلیم NCEP/NCAR R1 1991–2020 (NOAA PSL)', tclass='weekly'),
    'iri':   dict(label='IRI دانشگاه کلمبیا — پیش‌بینی فصلی احتمالاتی (سه‌دهکی)', name='IRI-SEASONAL', res='1° / 2.5°', cyc='ماهانه', prov='IRI, Columbia University (Data Library)', tclass='seasonal'),
}
PARAMS = {  # id: (فارسی، واحد، دسته، ترتیب، مقیاس)
    'wta': ('انومالی هفتگی دمای ۲ متری (°C)', '°C', 'tp', 20, 'wkta'),
    'wpa': ('انومالی هفتگی بارش (میلی‌متر در هفته)', 'mm', 'pr', 10, 'wkpa'),
    'tpp': ('پیش‌بینی فصلی بارش — دهک غالب و احتمال (٪)', '%', 'pr', 11, 'terp'),
    'tpt': ('پیش‌بینی فصلی دما — دهک غالب و احتمال (٪)', '%', 'tp', 21, 'tert'),
}
MPAR = {'ecwk': ('wta', 'wpa'), 'cfswk': ('wta', 'wpa'), 'iri': ('tpp', 'tpt')}

def begin(up, mk, run):
    M = MODELS[mk]; ps = MPAR[mk]
    return up.call('begin', js={'model': mk, 'run': f'{run:%Y%m%d%H}', 'name': M['name'], 'label': M['label'],
        'info': dict(tclass=M['tclass'], res=M['res'], cyc=M['cyc'], prov=M['prov']), 'cats': [dict(id=i, fa=f, o=o) for i, f, o in N.CATS],
        'scales': {PARAMS[p][4]: dict(c=styles.SC[PARAMS[p][4]]['colors'], e=[None if abs(x) == INF else x for x in styles.SC[PARAMS[p][4]]['edges']],
                                      lo=styles.SC[PARAMS[p][4]]['edges'][0] == -INF, hi=styles.SC[PARAMS[p][4]]['edges'][-1] == INF) for p in ps},
        'params': {p: dict(fa=PARAMS[p][0], unit=PARAMS[p][1], cat=PARAMS[p][2], o=PARAMS[p][3], sc=PARAMS[p][4], mu=PARAMS[p][1], alt='', me=1, ln=0) for p in ps}})

def put(up, mk, run, pid, vt, lead_h, field, have, nearest=False):
    fn = f'me/{pid}_{vt:%Y%m%d%H}.webp'
    if fn in have: return 0
    if not np.isfinite(field).any(): return 0
    dat, _ = N.render_me(None, field, PARAMS[pid][4]); up.put(mk, f'{run:%Y%m%d%H}', fn, dat, dict(r='me', m=mk, p=pid, s=int(lead_h), v=f'{vt:%Y%m%d%H}')); return 1

def regrid_nearest(arr, lon, lat):
    """برای میدان‌های رده‌ای (سه‌دهکی): نزدیک‌ترین همسایه، بدون رنگ میانی."""
    lon = np.asarray(lon, float) % 360; lat = np.asarray(lat, float); o = np.argsort(lon); lon, arr = lon[o], np.asarray(arr)[:, o]
    if lat[0] > lat[-1]: lat, arr = lat[::-1], arr[::-1]
    ix = np.clip(np.rint(np.interp(L.LON2 % 360, lon, np.arange(len(lon)))).astype(int), 0, len(lon) - 1)
    iy = np.clip(np.rint(np.interp(L.LAT2, lat, np.arange(len(lat)))).astype(int), 0, len(lat) - 1)
    return np.asarray(arr, np.float32)[iy, ix]

# ---------------------------------------------------------------- ۱) ECMWF EC46 هفتگی (Open-Meteo)
SAPI = 'https://seasonal-api.open-meteo.com/v1/seasonal'
def ec_weekly(mock=False):
    import requests
    STEP = 1.5; lo = np.arange(CROP[0], CROP[1] + 1e-6, STEP); la = np.arange(CROP[2], CROP[3] + 1e-6, STEP); LON, LAT = np.meshgrid(lo, la); fl, fa = LON.ravel(), LAT.ravel(); n = len(fl)
    if mock:
        t0 = datetime(2026, 10, 19, tzinfo=UTC); W = 6
        ta = np.stack([np.sin(LON / 7 + k) * 2.5 + (LAT - 30) * 0.05 for k in range(W)]).astype(np.float32); pa = np.stack([np.cos(LAT / 4 - k) * 12 for k in range(W)]).astype(np.float32)
        return t0, lo, la, ta, pa
    vars_ = 'temperature_2m_anomaly,precipitation_anomaly'; got = {}; t_ = None; unit = {}
    tdead = time.time() + 900                                  # r82: بودجهٔ زمانی کل دریافت EC46؛ بعد از ۱۰ دقیقه رها می‌شود (قبلاً ساعت‌ها در ReadTimeout می‌ماند)
    for model in ('ecmwf_ec46_ensemble_mean', 'ecmwf_ec46', None):
        got.clear(); ok = True; B = 10                           # r85: دسته‌های کوچک‌تر (۲۵ نقطه × اعضا از IP گیت‌هاب ReadTimeout می‌داد)
        for s in range(0, n, B):
            p = dict(latitude=','.join(f'{x:.2f}' for x in fa[s:s + B]), longitude=','.join(f'{x:.2f}' for x in fl[s:s + B]), weekly=vars_, timezone='GMT')
            if model: p['models'] = model
            j = None
            for k in range(2):
                if time.time() > tdead: break
                try:
                    r = requests.get(SAPI, params=p, timeout=(15, 120))
                    if r.status_code == 200: j = r.json(); break
                    log(f'  EC46 هفتگی HTTP {r.status_code}: {r.text[:160]}')
                    if r.status_code == 400: break
                except Exception as e: log(f'  {type(e).__name__}')
                time.sleep(4 * (k + 1))
            if j is None: ok = False; break
            if time.time() > tdead: ok = False; break
            for i, o in enumerate(j if isinstance(j, list) else [j]):
                w = o.get('weekly') or {}; unit.update(o.get('weekly_units') or {})
                if not w.get('time'): ok = False; break
                t_ = t_ or w['time']
                for key in ('temperature_2m_anomaly', 'precipitation_anomaly'):
                    v = w.get(key)
                    if v is None:      # اعضای جدا: میانگین اعضا
                        mem = [np.array([np.nan if x is None else x for x in w[k_]], float) for k_ in w if k_.startswith(key + '_member')]
                        v = np.nanmean(mem, 0) if mem else None
                    if v is None: ok = False; break
                    got.setdefault(key, {})[s + i] = np.array([np.nan if x is None else x for x in v], float)
                time.sleep(0.5)
            if not ok: break
        if ok and got: log(f'  EC46 هفتگی: مدل {model or "پیش‌فرض"}؛ واحدها {unit}'); break
    if not got or not t_: return None
    W = min(6, len(t_)); ta = np.full((W, n), np.nan, np.float32); pa = ta.copy()
    for i, v in got['temperature_2m_anomaly'].items(): ta[:, i] = v[:W]
    for i, v in got['precipitation_anomaly'].items(): pa[:, i] = v[:W]
    pu = str(unit.get('precipitation_anomaly', 'mm'))
    if 'day' in pu or '/d' in pu: pa *= 7.0                               # mm/day → mm/week
    t0 = datetime.strptime(t_[0][:10], '%Y-%m-%d').replace(tzinfo=UTC)
    return t0, lo, la, ta.reshape((W,) + LON.shape), pa.reshape((W,) + LON.shape)

# ---------------------------------------------------------------- ۲) CFSv2 هفتگی − اقلیم NCEP R1
CLIM_URLS = {'t': ['https://downloads.psl.noaa.gov/Datasets/ncep.reanalysis.derived/surface_gauss/air.2m.mon.ltm.1991-2020.nc', 'https://downloads.psl.noaa.gov/Datasets/ncep.reanalysis.derived/surface_gauss/air.2m.mon.ltm.nc'],
             'p': ['https://downloads.psl.noaa.gov/Datasets/ncep.reanalysis.derived/surface_gauss/prate.sfc.mon.ltm.1991-2020.nc', 'https://downloads.psl.noaa.gov/Datasets/ncep.reanalysis.derived/surface_gauss/prate.sfc.mon.ltm.nc']}
def nc_read(raw):
    try:
        import netCDF4; d = netCDF4.Dataset('mem', memory=raw); return {k: np.array(d.variables[k][:]) for k in d.variables}, {k: d.variables[k].dimensions for k in d.variables}
    except ImportError:
        from scipy.io import netcdf_file; f = netcdf_file(io.BytesIO(raw), mmap=False); return {k: np.array(f.variables[k][:]).copy() for k in f.variables}, {k: f.variables[k].dimensions for k in f.variables}
def ltm(kind):
    import requests
    for u in CLIM_URLS[kind]:
        try:
            r = requests.get(u, timeout=90)
            if r.status_code != 200: continue
            V, D = nc_read(r.content); name = 'air' if kind == 't' else 'prate'; a = V[name].astype(np.float32)
            if kind == 't' and np.nanmean(a) > 150: a = a - 273.15
            if kind == 'p': a = a * 86400.0                                        # kg m⁻² s⁻¹ → mm/day
            log(f'  اقلیم {kind}: {u.rsplit("/", 1)[-1]}'); return a, V['lon'], V['lat']
        except Exception as e: log(f'  اقلیم {kind} از {u}: {e}')
    return None
def clim_on(C, doy, lo, la):
    a, clon, clat = C; mid = np.array([15, 45, 74, 105, 135, 166, 196, 227, 258, 288, 319, 349], float)
    k = np.searchsorted(mid, doy) % 12; k0 = (k - 1) % 12; d0 = mid[k0] if mid[k0] <= doy else mid[k0] - 365; w = (doy - d0) / ((mid[k] if mid[k] >= doy else mid[k] + 365) - d0)
    f = (1 - w) * a[k0] + w * a[k]; lon = np.asarray(clon) % 360; lat = np.asarray(clat); o = np.argsort(lon); f = f[:, o]; lon = lon[o]
    if lat[0] > lat[-1]: lat, f = lat[::-1], f[::-1]
    from scipy.interpolate import RegularGridInterpolator
    I = RegularGridInterpolator((lat, lon), f, bounds_error=False, fill_value=np.nan); LO, LA = np.meshgrid(np.asarray(lo) % 360, la)
    return I(np.stack([LA.ravel(), LO.ravel()], 1)).reshape(LA.shape).astype(np.float32)
def cfs_weekly(mock=False):
    if mock:
        t0 = datetime(2026, 10, 21, tzinfo=UTC); lo = np.arange(CROP[0], CROP[1] + 0.1, 0.5); la = np.arange(CROP[2], CROP[3] + 0.1, 0.5); X, Y = np.meshgrid(lo, la)
        return t0, lo, la, np.stack([np.cos(X / 6 - k) * 3 for k in range(5)]).astype(np.float32), np.stack([np.sin(Y / 3 + k) * 15 for k in range(5)]).astype(np.float32)
    import ens_maps as E
    fs = E.S3(); run = E.cfs_pick_run(fs)
    if run is None: return None
    raw = E.cfs_collect(fs, run, 35, True); P = E.cfs_products(raw, 35)
    Ct, Cp = ltm('t'), ltm('p')
    if Ct is None or Cp is None: log('✗ CFS هفتگی: اقلیم NCEP خوانده نشد'); return None
    lo = la = None; TA, PA = [], []
    for w in range(5):
        days = [d for d in range(7 * w + 1, 7 * w + 8) if d in P and 't2m' in P[d] and 'p24' in P[d]]
        if len(days) < 7: break
        lo, la = P[days[0]]['t2m'][1], P[days[0]]['t2m'][2]
        t = np.mean([P[d]['t2m'][0] for d in days], 0); p = np.sum([P[d]['p24'][0] for d in days], 0)
        mid = run + timedelta(days=7 * w + 4); doy = mid.timetuple().tm_yday
        TA.append(t - clim_on(Ct, doy, lo, la)); PA.append(p - 7 * clim_on(Cp, doy, lo, la))
    if not TA: return None
    return run, lo, la, np.stack(TA).astype(np.float32), np.stack(PA).astype(np.float32)

def make_weekly(up, mk, R, a):
    t0, lo, la, ta, pa = R; run = t0.replace(hour=0, minute=0, second=0, microsecond=0)
    r = begin(up, mk, run); have = set(r.get('have', [])); made = 0
    for w in range(ta.shape[0]):
        vt = run + timedelta(days=7 * (w + 1)); lead = 24 * 7 * (w + 1)          # زمان معتبر = پایان هفته
        made += put(up, mk, run, 'wta', vt, lead, L.regrid(ta[w], lo, la), have)
        made += put(up, mk, run, 'wpa', vt, lead, L.regrid(pa[w], lo, la), have)
    up.wait(); up.call('end', js={'model': mk, 'run': f'{run:%Y%m%d%H}'}); log(f'✓ {mk}: {made} نقشه'); return made

# ---------------------------------------------------------------- ۳) IRI فصلی سه‌دهکی
IRI = 'https://iridl.ldeo.columbia.edu/SOURCES/.IRI/.FD/.NMME_Seasonal_Forecast/'
IRI_VARS = {'tpp': '.Precipitation_ELR/.prob', 'tpt': '.Temperature_ELR/.prob'}
def iri_fetch(path, mock=False):
    if mock:
        lo = np.arange(15, 75, 1.0); la = np.arange(5, 50, 1.0); X, Y = np.meshgrid(lo, la); out = []
        for l in range(4):
            b = 33 + 25 * np.sin(X / 9 + l) ; a = 33 + 25 * np.cos(Y / 7 - l); nrm = np.full_like(b, 34.0)
            out.append(np.stack([b, nrm, a]))
        return datetime(2026, 10, 1, tzinfo=UTC), [1.0, 2.0, 3.0, 4.0], lo, la, np.stack(out).astype(np.float32)
    import requests
    u = f'{IRI}{path}/X/{CROP[0]}/{CROP[1]}/RANGEEDGES/Y/{CROP[2]}/{CROP[3]}/RANGEEDGES/data.nc'
    r = None
    for k in range(2):                                         # r82: سرور IRI کند است؛ دو تلاش با timeout=(اتصال ۳۰، خواندن ۱۸۰) و بعد رها
        try: r = requests.get(u, timeout=(30, 180), headers={'User-Agent': 'MetStat-iri/1.0'}); r.raise_for_status(); break
        except Exception as e: log(f'  IRI تلاش {k + 1}: {type(e).__name__}'); r = None
    if r is None: raise RuntimeError('IRI پاسخ نداد')
    V, D = nc_read(r.content); var = 'prob' if 'prob' in V else [k for k in V if len(D[k]) >= 4][0]; dims = list(D[var]); a = V[var].astype(np.float32)
    tdim = [d for d in dims if d not in ('X', 'Y', 'C', 'L')][0]; t = V[tdim]
    # آخرین زمان صدور که داده دارد
    ti = a.shape[dims.index(tdim)] - 1
    while ti > 0 and not np.isfinite(np.take(a, ti, axis=dims.index(tdim))).any(): ti -= 1
    a = np.take(a, ti, axis=dims.index(tdim)); dims.remove(tdim)
    a = np.transpose(a, [dims.index('L'), dims.index('C'), dims.index('Y'), dims.index('X')])
    if np.nanmax(a) <= 1.0001: a = a * 100
    issue = datetime(1960, 1, 1, tzinfo=UTC) + timedelta(days=30.4375 * float(t[ti]))       # «ماه از ۱۹۶۰» (قرارداد IRIDL)
    issue = issue.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return issue, [float(x) for x in V['L']], V['X'], V['Y'], a
def dominant(a3):
    """a3: [C=3,Y,X] درصد (پایین، نرمال، بالا) → مقدار علامت‌دار برای نقشه."""
    b, n, u = a3; k = np.argmax(np.stack([np.nan_to_num(b, nan=-1), np.nan_to_num(n, nan=-1), np.nan_to_num(u, nan=-1)]), 0)
    p = np.where(k == 0, b, np.where(k == 2, u, n)); v = np.where(k == 0, -p, np.where(k == 2, p, 0.0))
    v = np.where((k != 1) & (p < 40), np.sign(v) * 1.0, v)                # کمتر از ۴۰٪ = بدون برتری (سفید)
    return np.where(np.isnan(b) | np.isnan(u), np.nan, v).astype(np.float32)
def make_iri(up, a):
    data = {}
    for pid, path in IRI_VARS.items():
        try: data[pid] = iri_fetch(path, a.mock)
        except Exception as e: log(f'✗ IRI {pid}: {e}')
    if not data: return 0
    issue = list(data.values())[0][0]; r = begin(up, 'iri', issue); have = set(r.get('have', [])); made = 0
    for pid, (iss, Ls, X, Y, A) in data.items():
        for li, l in enumerate(Ls):
            start = (iss.replace(day=1) + timedelta(days=31 * int(round(l)))).replace(day=1)       # آغاز فصل هدف (L=1 ⇒ ماه بعد)
            made += put(up, 'iri', issue, pid, start, 24 * 30 * int(round(l)), regrid_nearest(dominant(A[li]), X, Y), have)
    up.wait(); up.call('end', js={'model': 'iri', 'run': f'{issue:%Y%m%d%H}'}); log(f'✓ iri: {made} نقشه'); return made

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--host'); ap.add_argument('--key', default=''); ap.add_argument('--out'); ap.add_argument('--mock', action='store_true'); ap.add_argument('--only', default='ecwk,cfswk,iri')
    a = ap.parse_args()
    if not a.host and not a.out: sys.exit('--host یا --out لازم است')
    up = N.Uploader(a.host, a.key, a.out); only = set(a.only.split(',')); tot = 0
    if 'ecwk' in only:
        try:
            R = ec_weekly(a.mock); tot += make_weekly(up, 'ecwk', R, a) if R else 0
            if not R: log('✗ ecwk: انومالی هفتگی از Open-Meteo گرفته نشد (نام متغیر یا مدل را در لاگ ببینید)')
        except Exception as e: log(f'✗ ecwk: {e}')
    if 'cfswk' in only:
        try:
            R = cfs_weekly(a.mock); tot += make_weekly(up, 'cfswk', R, a) if R else 0
            if not R: log('✗ cfswk: ساخته نشد')
        except Exception as e: log(f'✗ cfswk: {e}')
    if 'iri' in only:
        try: tot += make_iri(up, a)
        except Exception as e: log(f'✗ iri: {e}')
    log(f'پایان: {tot} نقشه'); sys.exit(0)

if __name__ == '__main__': main()

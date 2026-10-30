# -*- coding: utf-8 -*-
"""r127 پروب ۲: (۱) ساختار GEM زیر پوشهٔ تاریخ‌دار MSC؛ (۲) آزمایش واقعی ICON جهانی: دانلود+bz2+eccodes+درون‌یابی از شبکهٔ مثلثی به شبکهٔ منظم، با زمان‌سنجی و مقایسه با ICON-EU در چند شهر."""
import re, bz2, time, io, os, tempfile, datetime as dt, requests, numpy as np
UTC = dt.timezone.utc; S = requests.Session(); S.headers['User-Agent'] = 'metstat-probe/1.0'
def ls(u, n=60):
    try: r = S.get(u, timeout=40)
    except Exception as e: print('ERR', u, e); return []
    print(f'GET {u} -> {r.status_code}')
    if not r.ok: return []
    L = re.findall(r'href="([^"?/][^"]*/?)"', r.text); print(f'   {len(L)}:', L[:n]); return L
now = dt.datetime.now(UTC); print('now', now.isoformat())
print('\n##### GEM: آخرین پوشهٔ تاریخ‌دار')
root = 'https://dd.weather.gc.ca/'; days = sorted(x for x in ls(root, 3) if re.match(r'\d{8}/', x))
print('   last days:', days[-4:])
for d in days[-2:][::-1]:
    a = ls(root + d, 20)
    for sub in ('WXO-DD/', ''):
        b = ls(root + d + sub, 40)
        gem = [x for x in b if 'gem' in x or 'model' in x]
        for g in gem[:6]: ls(root + d + sub + g, 20)
        if any('model_gem_global' in x for x in b):
            base = root + d + sub + 'model_gem_global/'
            ls(base, 20); ls(base + '15km/', 20); ls(base + '15km/grib2/', 20); c = ls(base + '15km/grib2/lat_lon/', 20)
            for hh in [x for x in c if re.match(r'\d\d/', x)][:4]:
                s0 = ls(base + '15km/grib2/lat_lon/' + hh, 8)
                f = ls(base + '15km/grib2/lat_lon/' + hh + '000/', 120)
                for x in f:
                    if re.search(r'(APCP|TMP_TGL_2|PRMSL|HGT_ISBL_0500|RH_TGL_2|UGRD_TGL_10|ASNOW|CAPE|WIND_TGL_10)', x):
                        try:
                            h = S.head(base + '15km/grib2/lat_lon/' + hh + '000/' + x, timeout=30); print('   HEAD', x, h.status_code, h.headers.get('Content-Length'), h.headers.get('Last-Modified'))
                        except Exception as e: print('   ERR', e)
            raise SystemExit if False else None
            break
    break
print('\n##### ICON global: دانلود و درون‌یابی T_2M step 0 (+ clat/clon)')
try:
    import eccodes as ec
    from scipy.spatial import cKDTree
    base = 'https://opendata.dwd.de/weather/nwp/icon/grib/'
    cyc = None
    for back in range(0, 30, 6):
        t = (now - dt.timedelta(hours=back)).replace(minute=0, second=0, microsecond=0); hh = (t.hour // 6) * 6; run = t.replace(hour=hh)
        u = f'{base}{hh:02d}/t_2m/icon_global_icosahedral_single-level_{run:%Y%m%d%H}_000_T_2M.grib2.bz2'
        h = S.head(u, timeout=30)
        if h.ok: cyc = (run, u, h.headers.get('Last-Modified')); break
    print('latest run with step0:', cyc)
    run, u, lm = cyc
    def fetch(url):
        t0 = time.time(); r = S.get(url, timeout=120); r.raise_for_status(); raw = bz2.decompress(r.content); t1 = time.time()
        p = os.path.join(tempfile.gettempdir(), 'x.grib2'); open(p, 'wb').write(raw)
        f = open(p, 'rb'); g = ec.codes_grib_new_from_file(f); v = ec.codes_get_values(g); ec.codes_release(g); f.close()
        print(f'   {url.split("/")[-1]}: {len(r.content)/1e6:.1f} MB bz2, {len(v)} values, dl+bz2 {t1-t0:.1f}s, grib {time.time()-t1:.1f}s'); return v
    clat = fetch(f'{base}00/clat/icon_global_icosahedral_time-invariant_{run:%Y%m%d}00_CLAT.grib2.bz2') if False else fetch(f'{base}{run.hour:02d}/clat/icon_global_icosahedral_time-invariant_{run:%Y%m%d%H}_CLAT.grib2.bz2')
    clon = fetch(f'{base}{run.hour:02d}/clon/icon_global_icosahedral_time-invariant_{run:%Y%m%d%H}_CLON.grib2.bz2')
    t2 = fetch(u)
    print('   clat range', float(clat.min()), float(clat.max()), '(rad?)  t2 range', float(t2.min()), float(t2.max()))
    la = np.degrees(clat) if abs(clat).max() < 4 else clat; lo = np.degrees(clon) if abs(clon).max() < 8 else clon
    m = (la > 5) & (la < 67) & (lo > -17) & (lo < 73)
    xyz = lambda a, b: np.stack([np.cos(np.radians(a)) * np.cos(np.radians(b)), np.cos(np.radians(a)) * np.sin(np.radians(b)), np.sin(np.radians(a))], 1)
    t0 = time.time(); tree = cKDTree(xyz(la[m], lo[m]))
    pts = {'Tehran': (35.69, 51.39), 'Shiraz': (29.59, 52.58), 'Tabriz': (38.08, 46.29), 'Mashhad': (36.3, 59.6)}
    d, i = tree.query(xyz(*map(np.array, zip(*pts.values()))) if False else xyz(np.array([p[0] for p in pts.values()]), np.array([p[1] for p in pts.values()])), k=3)
    w = 1 / np.maximum(d, 1e-9); w /= w.sum(1, keepdims=True); val = (t2[m][i] * w).sum(1) - 273.15
    print(f'   KD-tree build+query {time.time()-t0:.1f}s; ICON-global T2m C:', dict(zip(pts, np.round(val, 1))))
    ue = f'https://opendata.dwd.de/weather/nwp/icon-eu/grib/{run.hour:02d}/t_2m/icon-eu_europe_regular-lat-lon_single-level_{run:%Y%m%d%H}_000_T_2M.grib2.bz2'
    r = S.get(ue, timeout=120)
    if r.ok:
        open('/tmp/e.grib2', 'wb').write(bz2.decompress(r.content)); f = open('/tmp/e.grib2', 'rb'); g = ec.codes_grib_new_from_file(f)
        ni, nj = ec.codes_get(g, 'Ni'), ec.codes_get(g, 'Nj'); lat1, lon1 = ec.codes_get(g, 'latitudeOfFirstGridPointInDegrees'), ec.codes_get(g, 'longitudeOfFirstGridPointInDegrees')
        di, dj = ec.codes_get(g, 'iDirectionIncrementInDegrees'), ec.codes_get(g, 'jDirectionIncrementInDegrees'); sc = ec.codes_get(g, 'jScansPositively'); v = ec.codes_get_values(g).reshape(nj, ni)
        print('   ICON-EU grid', ni, nj, lat1, lon1, di, dj, 'jScansPositively', sc)
        out = {}
        for k, (a, b) in pts.items():
            jj = int(round((a - lat1) / (dj if sc else -dj))); ii = int(round((b - lon1) / di))
            out[k] = round(float(v[jj, ii]) - 273.15, 1) if 0 <= jj < nj and 0 <= ii < ni else None
        print('   ICON-EU T2m C:', out)
    print('   uploaded-at (Last-Modified step0):', lm, ' | وقت اجرا:', run.isoformat())
except Exception as e:
    import traceback; traceback.print_exc()

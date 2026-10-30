# -*- coding: utf-8 -*-
"""r127 — پروب منابع رسمی GEM (MSC Datamart) و ICON (DWD Open Data): ساختار پوشه‌ها، نام فایل‌ها، زمان انتشار هر ران و مقایسه با Open-Meteo.
اجرا: GitHub Actions → src-probe → Run workflow؛ خروجی را (log) برای ادامهٔ کار بفرستید. هیچ کلید یا رمزی چاپ نمی‌شود."""
import re, sys, datetime as dt, requests
UTC = dt.timezone.utc
S = requests.Session(); S.headers['User-Agent'] = 'metstat-probe/1.0'
def get(u, **k):
    try: r = S.get(u, timeout=40, **k); return r
    except Exception as e: print('  ERR', u, type(e).__name__, e); return None
def ls(u, pat=r'href="([^"?/][^"]*/?)"', n=40):
    r = get(u)
    if r is None: return []
    print(f'GET {u} -> {r.status_code}')
    if not r.ok: return []
    L = re.findall(pat, r.text); print(f'   {len(L)} entries:', L[:n]); return L
def head(u):
    try:
        r = S.head(u, timeout=40, allow_redirects=True); print(f'HEAD {u} -> {r.status_code} size={r.headers.get("Content-Length")} lm={r.headers.get("Last-Modified")}'); return r
    except Exception as e: print('  ERR', u, e)
print('=== now', dt.datetime.now(UTC).isoformat())
print('\n##### GEM / MSC Datamart')
for base in ('https://dd.weather.gc.ca/', 'https://dd.weather.gc.ca/today/model_gem_global/', 'https://dd.weather.gc.ca/model_gem_global/'):
    ls(base, n=25)
for root in ('https://dd.weather.gc.ca/today/model_gem_global/15km/grib2/lat_lon/', 'https://dd.weather.gc.ca/model_gem_global/15km/grib2/lat_lon/'):
    cyc = ls(root)
    for c in cyc[:4]:
        sub = ls(root + c, n=12)
        if sub:
            f = ls(root + c + sub[min(1, len(sub) - 1)], n=80)
            for x in f:
                if re.search(r'APCP|TMP_TGL_2_|PRMSL|HGT_ISBL_0500', x): head(root + c + sub[min(1, len(sub) - 1)] + x)
            break
print('\n##### DWD ICON global')
for root in ('https://opendata.dwd.de/weather/nwp/icon/grib/', 'https://opendata.dwd.de/weather/nwp/icon-eu/grib/'):
    cyc = ls(root, n=10)
    for c in [x for x in cyc if re.match(r'\d\d/', x)]:
        sub = ls(root + c, n=40)
        for v in [x for x in sub if re.match(r'(tot_prec|t_2m|pmsl|clat|clon)/', x)][:5]:
            f = ls(root + c + v, n=6)
            for x in f[:2]: head(root + c + v + x)
        break
print('\n##### DWD ICON grids / weights')
ls('https://opendata.dwd.de/weather/nwp/icon/grib/00/', n=60)
ls('https://opendata.dwd.de/weather/lib/cdo/', n=40)
print('\n##### Open-Meteo S3 (مقایسه)')
try:
    import s3fs
    fs = s3fs.S3FileSystem(anon=True)
    for d in ('dwd_icon', 'cmc_gem_gdps', 'cmc_gem_gdps_15km'):
        try:
            for p in fs.ls(f'openmeteo/data/{d}/static')[:6]: print(' ', p)
        except Exception as e: print('  ', d, type(e).__name__, e)
except Exception as e: print('s3fs', e)
print('\n##### eccodes / pygrib در Actions')
for m in ('eccodes', 'cfgrib', 'pygrib', 'xarray'):
    try: __import__(m); print(' ', m, 'OK')
    except Exception as e: print(' ', m, 'MISSING')

import re, requests, datetime as dt
S = requests.Session(); S.headers['User-Agent'] = 'metstat-probe/1.0'
def ls(u, n=80):
    try: r = S.get(u, timeout=40)
    except Exception as e: print('ERR', u, e); return []
    print(f'GET {u} -> {r.status_code}')
    if not r.ok: return []
    L = re.findall(r'href="([^"?/][^"]*/?)"', r.text); print(f'   {len(L)}:', L[:n]); return L
d = max(x for x in ls('https://dd.weather.gc.ca/', 2) if re.match(r'\d{8}/', x)); print('day', d)
for res in ('15km/', '10km/'):
    b = f'https://dd.weather.gc.ca/{d}WXO-DD/model_gdps/{res}'
    ls(b, 20); ls(b + 'grib2/', 20); c = ls(b + 'grib2/lat_lon/', 20)
    for hh in ('00/', '12/', '18/', '06/'):
        s = ls(b + 'grib2/lat_lon/' + hh, 12)
        if not s: continue
        f = ls(b + 'grib2/lat_lon/' + hh + '000/', 150)
        for x in f:
            if re.search(r'(APCP|TMP_TGL_2_|PRMSL|HGT_ISBL_0500|RH_TGL_2_|UGRD_TGL_10|VGRD_TGL_10|CAPE|WIND_TGL_10|ASNOW|WEASN)', x):
                h = S.head(b + 'grib2/lat_lon/' + hh + '000/' + x, timeout=30); print('   HEAD', x, h.status_code, h.headers.get('Content-Length'), h.headers.get('Last-Modified'))
        l = ls(b + 'grib2/lat_lon/' + hh, 400); print('   hours dirs:', len(l))
        break
print(dt.datetime.utcnow().isoformat())

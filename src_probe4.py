import re, requests, datetime as dt
S = requests.Session(); S.headers['User-Agent'] = 'metstat-probe/1.0'
def ls(u, n=60):
    try: r = S.get(u, timeout=40)
    except Exception as e: print('ERR', u, e); return []
    print(f'GET {u} -> {r.status_code}')
    if not r.ok: return []
    L = re.findall(r'href="([^"?/][^"]*/?)"', r.text); print(f'   {len(L)}:', L[:n]); return L
KEY = r'(APCP|TMP_|PRMSL|HGT_|RH_|UGRD|VGRD|CAPE|WIND|WEASN|ASNOW|SNOW|GUST|VVEL|DZDT|PWAT)'
d = max(x for x in ls('https://dd.weather.gc.ca/', 2) if re.match(r'\d{8}/', x))
for res in ('15km/', '10km/'):
    b = f'https://dd.weather.gc.ca/{d}WXO-DD/model_gdps/{res}'
    cyc = ls(b)
    for c in cyc[:2]:
        s = ls(b + c, 40)
        for h in [x for x in s if re.match(r'\d+/', x)][:1] + [x for x in s if re.match(r'\d+/', x)][-1:]:
            f = ls(b + c + h, 400)
            hd = 0
            for x in f:
                if re.search(KEY, x) and hd < 40:
                    r = S.head(b + c + h + x, timeout=30); print('   HEAD', x, r.status_code, r.headers.get('Content-Length'), r.headers.get('Last-Modified')); hd += 1
print(dt.datetime.now(dt.timezone.utc).isoformat())

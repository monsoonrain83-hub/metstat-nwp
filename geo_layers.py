#!/usr/bin/env python3
"""geo_layers.py — ساخت لایه‌های جغرافیایی سایت MetStat (یک‌بار؛ لازم به اجرای روزانه نیست)
خروجی: <out>/geo.json  →  روی هاست: online/data/geo.json
  places : [fa, lat, lon, level, pop, kind]   level 0=مرکز استان/پایتخت، 1=مرکز شهرستان/شهر بزرگ، 2=شهر، 3=شهر کوچک/روستای بزرگ، 4=روستا
  lakes  : [{n, en, r:[[ [lon,lat],... ], ...]}]   (حلقه‌های بستهٔ دریاچه)
  rivers : [{n, l:[[ [lon,lat],... ], ...]}]
  rivers: rk 0=خاورمیانه، 1=ایران، 2=استان، 3=شهرستان/مسیل اصلی
  borders: [[[lon,lat],...]] مرز خشکی کشورها (Natural Earth)
  coast  : [[[lon,lat],...]] ساحل بیرون از کادر خاورمیانه (برای کادر اروپا؛ r65)
  roads  : [{c, l:[[lon,lat],...]}]  c=1 آزادراه، 2=جادهٔ اصلی ملی، 3=جادهٔ اصلی استانی
منابع: GeoNames (CC-BY 4.0) برای مکان‌ها؛ OpenStreetMap (ODbL، © OpenStreetMap contributors) برای دریاچه/رود/جاده.
هر بخش مستقل است: اگر منبعی در دسترس نبود فقط همان بخش خالی می‌ماند و اجرا خطا نمی‌دهد.
"""
import argparse, io, json, math, os, re, sys, time, zipfile, datetime

def log(*a): print(time.strftime('%H:%M:%S'), *a, flush=True)
UA = {'User-Agent': 'MetStat-geo/1.0 (wtafkik.ir)'}

def get(url, data=None, timeout=300, tries=3):
    import requests
    last = None
    for k in range(tries):
        try:
            r = requests.post(url, data=data, headers=UA, timeout=timeout) if data is not None else requests.get(url, headers=UA, timeout=timeout)
            r.raise_for_status(); return r.content
        except Exception as e:
            last = e; time.sleep(4 * (k + 1))
    raise RuntimeError(f'{url[:60]}: {last}')

# ---------- ساده‌سازی (Douglas–Peucker) ----------
def dp(pts, eps):
    if len(pts) < 3: return pts
    keep = [False] * len(pts); keep[0] = keep[-1] = True; st = [(0, len(pts) - 1)]
    while st:
        a, b = st.pop(); (x1, y1), (x2, y2) = pts[a], pts[b]; dx, dy = x2 - x1, y2 - y1; L = dx * dx + dy * dy; mx, mi = -1, -1
        for i in range(a + 1, b):
            x, y = pts[i]
            d = abs((x - x1) * dy - (y - y1) * dx) / math.sqrt(L) if L else math.hypot(x - x1, y - y1)
            if d > mx: mx, mi = d, i
        if mx > eps: keep[mi] = True; st += [(a, mi), (mi, b)]
    return [p for p, k in zip(pts, keep) if k]

def rnd(pts): return [[round(x, 3), round(y, 3)] for x, y in pts]

# ---------- r131: پاکسازی نام و مختصات مکان‌ها (هم‌ارز geoCleanPlaces/geoFixDedup سایت) ----------
CNT_EXTRA = "ممسنی بوانات بختگان رستم کوار خفر پاسارگاد زرین‌دشت سروستان قیر کارزین سپیدان مهر گراش لامرد فراشبند خرم‌بید ارسنجان اقلید بیضا سرچهان دشتستان تنگستان دیر کنگان جم گناوه دشتی بهمئی کهگیلویه بویراحمد گچساران باشت چرام لنده دنا بن کیار سامان بروجن لردگان اردل کوهرنگ فارسان خانمیرزا مبارکه نجف‌آباد لنجان فلاورجان شاهین‌شهر میمه خمینی‌شهر تیران کرون نطنز کاشان آران بیدگل اردستان خوانسار گلپایگان خور بیابانک سمیرم دهاقان شهرضا برخوار چادگان فریدن فریدونشهر عسلویه خنج لارستان لار داراب فسا جهرم نی‌ریز استهبان مرودشت کازرون آباده شیراز".split()
GEN = {'بالا', 'پایین', 'علیا', 'سفلی', 'میانی', 'وسطی', 'سفلا', 'علیای', 'جدید', 'قدیم', 'نو', 'کهنه'}
FIX = [(re.compile(r'^سد ?درودزن$'), 30.19, 52.44), (re.compile(r'^ازنا$'), 33.4564, 49.4565), (re.compile(r'^زارچ$'), 31.7515, 54.2245)]   # نقاط شناخته‌شدهٔ جابه‌جا در GeoNames
def _nrm(t): return re.sub(r'[\s\u200c]+', '', str(t or '')).replace('ي', 'ی').replace('ك', 'ک')
def county_set():
    S = {_nrm(x) for x in CNT_EXTRA}
    try:
        for q in json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'id_seats.json'), encoding='utf8')): S.add(_nrm(q[0]))
    except Exception as e: log('  id_seats.json خوانده نشد (فقط فهرست تکمیلی شهرستان‌ها):', e)
    return S
def clean_name(n, lv, S):
    if lv < 3: return n
    tk = n.strip().split()
    if len(tk) < 2 or _nrm(tk[-1]) not in S: return n
    base = ' '.join(tk[:-1])
    if len(_nrm(base)) < 2 or (len(tk) == 2 and _nrm(tk[0]) in {_nrm(g) for g in GEN}): return n
    return base
def clean_places(res, ref=()):
    """ref: [(نام، lat، lon)] مراکز/ایستگاه‌های مرجع؛ خروجی: لیست پاک‌شده + گزارش (hم‌نام‌های حذف‌شده و اصلاح‌ها)."""
    S = county_set(); rep = []; out = []
    for p in res:
        p = list(p); q = clean_name(p[0], p[3], S)
        if q != p[0]: rep.append(f'نام: {p[0]} → {q}'); p[0] = q
        for rx, la, lo in FIX:
            if rx.match(re.sub(r'\s+', ' ', p[0]).strip()): rep.append(f'مختصات {p[0]}: {p[1]},{p[2]} → {la},{lo}'); p[1], p[2] = la, lo
        out.append(p)
    refd = {}
    for n, la, lo in ref: refd.setdefault(_nrm(n), []).append((la, lo))
    def near(p):
        b = 9.0
        for la, lo in refd.get(_nrm(p[0]), []): b = min(b, math.hypot(p[1] - la, (p[2] - lo) * .87))
        return b
    by = {}
    for p in out: by.setdefault(_nrm(p[0]), []).append(p)
    keep_ids = set()
    for k, a in by.items():
        keep = []
        for p in sorted(a, key=lambda x: (near(x), -x[4])):
            if any(math.hypot(p[1] - q[1], (p[2] - q[2]) * .87) < 0.3 for q in keep): rep.append(f'هم‌نام نزدیک حذف شد: {p[0]} {p[1]},{p[2]}'); continue
            keep.append(p)
        keep_ids.update(id(x) for x in keep)
    res2 = [p for p in out if id(p) in keep_ids]
    log(f'  پاکسازی نام/هم‌نام: {len(rep)} مورد؛ {len(out) - len(res2)} نقطهٔ تکراری حذف شد')
    return res2, rep

# ---------- مکان‌ها (GeoNames) ----------
KIND = {'PPLC': 'cap', 'PPLA': 'prov', 'PPLA2': 'cty', 'PPLA3': 'cty', 'PPLA4': 'sub'}
SEAT_REF = []
try: SEAT_REF = [(q[0], q[1], q[2]) for q in json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'id_seats.json'), encoding='utf8'))]
except Exception: pass
def places(maxn):
    zi = zipfile.ZipFile(io.BytesIO(get('https://download.geonames.org/export/dump/IR.zip')))
    rows = []
    for ln in zi.read('IR.txt').decode('utf8').splitlines():
        c = ln.split('\t')
        if len(c) < 15 or c[6] != 'P': continue
        rows.append((int(c[0]), c[1], float(c[4]), float(c[5]), c[7], int(c[14] or 0)))
    log(f'  GeoNames: {len(rows)} مکان مسکونی')
    za = zipfile.ZipFile(io.BytesIO(get('https://download.geonames.org/export/dump/alternatenames/IR.zip')))
    fa = {}; want = {r[0] for r in rows}
    for ln in za.read('IR.txt').decode('utf8').splitlines():
        c = ln.split('\t')
        if len(c) < 4 or c[2] != 'fa': continue
        g = int(c[1])
        if g not in want: continue
        if len(c) > 7 and c[7] == '1': continue                      # تاریخی
        if g not in fa or (len(c) > 4 and c[4] == '1'): fa[g] = c[3]  # ترجیح نام ترجیحی
    log(f'  نام فارسی برای {len(fa)} مکان')
    out = []
    for g, name, lat, lon, code, pop in rows:
        n = fa.get(g)
        if not n: continue
        n = re.sub(r'\s+', ' ', n.replace('ي', 'ی').replace('ك', 'ک')).strip()
        if code in ('PPLC', 'PPLA'): lv = 0
        elif code in ('PPLA2', 'PPLA3') or pop >= 150000: lv = 1
        elif code == 'PPLA4' or pop >= 25000: lv = 2
        elif pop >= 4000: lv = 3
        else: lv = 4
        out.append([n, round(lat, 4), round(lon, 4), lv, pop, KIND.get(code, 'pl')])
    out.sort(key=lambda p: (p[3], -p[4]))
    lim = [10 ** 9, 10 ** 9, 10 ** 9, 6000, maxn]; res = []; cnt = [0] * 5
    for p in out:
        if cnt[p[3]] >= lim[p[3]]: continue
        cnt[p[3]] += 1; res.append(p)
    res, rep = clean_places(res, SEAT_REF)
    try: open('geo_clean_report.txt', 'w', encoding='utf8').write('\n'.join(rep))
    except Exception: pass
    log('  مکان‌ها بر حسب سطح:', cnt); return res

# ---------- OSM (Overpass) ----------
OVP = ['https://overpass-api.de/api/interpreter', 'https://overpass.kumi.systems/api/interpreter', 'https://overpass.private.coffee/api/interpreter']
def overpass(q):
    last = None
    for u in OVP:
        try: return json.loads(get(u, data={'data': q}, timeout=240, tries=2))
        except Exception as e: last = e; log(f'  … Overpass {u.split("/")[2]}: {str(e)[:100]}')
    raise RuntimeError(f'Overpass در دسترس نیست: {last}')

def chain(ways):
    """چند خط → حلقه‌ها/زنجیره‌ها با اتصال سر و ته"""
    segs = [list(w) for w in ways if len(w) > 1]; out = []
    while segs:
        cur = segs.pop(); ok = True
        while ok:
            ok = False
            for i, s in enumerate(segs):
                if s[0] == cur[-1]: cur += s[1:]
                elif s[-1] == cur[-1]: cur += s[::-1][1:]
                elif s[-1] == cur[0]: cur = s[:-1] + cur
                elif s[0] == cur[0]: cur = s[::-1][:-1] + cur
                else: continue
                segs.pop(i); ok = True; break
        out.append(cur)
    return out

def geom_of(el):
    """عنصر OSM با out geom → فهرست خط‌ها [(lon,lat)...]"""
    if el['type'] == 'way': return [[(p['lon'], p['lat']) for p in el.get('geometry', [])]]
    return [[(p['lon'], p['lat']) for p in m.get('geometry', [])] for m in el.get('members', []) if m.get('type') == 'way' and m.get('role', 'outer') in ('outer', '', 'main_stream', 'side_stream')]

LAKES = [  # (نام فارسی، نام انگلیسی، regex نام فارسی در OSM)
    ('دریاچه ارومیه', 'Lake Urmia', '^(دریاچه )?(ارومیه|ارومیّه)$'),
    ('دریاچه بختگان', 'Lake Bakhtegan', '^(دریاچه )?بختگان$'),
    ('دریاچه طشک', 'Lake Tashk', '^(دریاچه )?طشک$'),
    ('دریاچه مهارلو', 'Lake Maharloo', '^(دریاچه )?مهارلو$'),
    ('دریاچه حوض سلطان', 'Hoze Soltan Lake', '^(دریاچه )?حوض سلطان$'),
    ('دریاچه نمک', 'Namak Lake (Daryacheh-ye Namak)', '^(دریاچه )?نمک$'),
    ('هامون', 'Hamun Lake', '^(دریاچه )?(هامون|هامون هیرمند|هامون پوزک|هامون صابری)$'),
]
def lakes():
    out = []
    for fa, en, rx in LAKES:
        q = f'[out:json][timeout:120];area["ISO3166-1"="IR"]->.a;(way["natural"="water"]["name"~"{rx}"](area.a);relation["natural"="water"]["name"~"{rx}"](area.a);way["natural"="water"]["name:fa"~"{rx}"](area.a);relation["natural"="water"]["name:fa"~"{rx}"](area.a););out geom;'
        try: d = overpass(q)
        except Exception as e: log(f'  ✗ {fa}: {e}'); continue
        rings = []
        for el in d.get('elements', []):
            for r in chain(geom_of(el)):
                if len(r) >= 4: rings.append(rnd(dp(r, 0.004)))
        rings = [r for r in rings if len(r) >= 4]
        if rings: out.append({'n': fa, 'en': en, 'r': rings}); log(f'  ✓ {fa}: {len(rings)} حلقه')
        else: log(f'  ✗ {fa}: در OSM پیدا نشد')
        time.sleep(2)
    return out

# ---------- رودها: فقط رودهای دائمیِ مهم؛ رتبه برای نمایش بر حسب زوم ----------
# رتبه ۰: زوم خاورمیانه | ۱: زوم ایران (فهرست کاربر) | ۲: زوم استان | ۳: زوم شهرستان (رودهای کوچک‌تر و مسیل‌های اصلی)
ME_RIVERS = [('دجله', 'Tigris', r'^(Tigris|Dijlah|دجله|Nahr Dijla)$'), ('فرات', 'Euphrates', r'^(Euphrates|Al-Furat|فرات|Nahr al-Furat|Fırat)$'), ('کارون', 'Karun', r'^(Karun|Karoun|کارون|رود کارون)$')]
IR_RIVERS = [  # (نام، regex نام فارسی/انگلیسی در OSM)
    ('کارون', '^(رود )?کارون$|^Karun$'), ('کرخه', '^(رود )?کرخه$|^Karkheh$'), ('دز', '^(رود )?دز$|^Dez$'), ('کُر', '^(رود )?(کر|کُر|کور)$|^Kor$|^Kur$'),
    ('جراحی', '^(رود )?جراحی$|^Jarrahi$'), ('سفیدرود', '^(رود )?سفید ?رود$|^Sefidrud$|^Sefid'), ('دالکی', '^(رود )?دالکی$|^Dalaki$'), ('قره‌آغاج', '^(رود )?قره ?(آغاج|آقاج|اغاج)$|^Mond$|^Qareh'),
    ('اترک', '^(رود )?اترک$|^Atrak$|^Atrek$'), ('هریرود', '^(رود )?هری ?رود$|^Harirud$|^Hari'), ('هلیل‌رود', '^(رود )?هلیل ?رود$|^Halil'), ('زاینده‌رود', '^(رود )?زاینده ?رود$|^Zayandeh'),
    ('رود کرج', '^(رود )?(کرج|رودخانه کرج)$|^Karaj'), ('ارس', '^(رود )?(ارس|اراس)$|^Aras$|^Araks$'), ('قزل‌اوزن', '^(رود )?قزل ?اوزن$|^Qezel'), ('هیرمند', '^(رود )?هیرمند$|^Helmand$|^Hirmand$'),
    ('زهره', '^(رود )?زهره$|^Zohreh$'), ('مند', '^(رود )?مند$'), ('گرگان‌رود', '^(رود )?گرگان ?رود$|^Gorgan'), ('تجن', '^(رود )?(تجن|تژن)$'),
    ('هراز', '^(رود )?هراز$|^Haraz$'), ('جاجرود', '^(رود )?جاجرود$|^Jajrud$'), ('کشف‌رود', '^(رود )?کشف ?رود$|^Kashaf'),
]
def hav(l):
    t = 0.0
    for (x1, y1), (x2, y2) in zip(l, l[1:]):
        t += math.hypot((x2 - x1) * math.cos(math.radians((y1 + y2) / 2)), y2 - y1) * 111.0
    return t

def river_tile(q):
    d = overpass(q); out = []
    for el in d.get('elements', []):
        t = el.get('tags', {}); nm = (t.get('name:fa') or t.get('name') or '').strip(); en = t.get('name:en', '')
        ws = geom_of(el) if el['type'] == 'relation' else geom_of(el)
        out.append((nm, en, t.get('intermittent') == 'yes' or t.get('seasonal') == 'yes', ws))
    return out

def rivers():
    res = {}                                                         # نام → dict(rk, lines, len)
    def add(nm, en, rk, ws, inter=False):
        r = res.setdefault(nm, dict(n=nm, en=en, rk=rk, w=[], inter=inter)); r['rk'] = min(r['rk'], rk); r['w'] += ws
    # ۱) رودهای رتبهٔ ۰ (خاورمیانه) — جعبهٔ بزرگ منطقه
    for fa, en, rx in ME_RIVERS:
        q = f'[out:json][timeout:200][bbox:12,25,42,65];(way["waterway"="river"]["name:en"~"{rx}"];way["waterway"="river"]["name"~"{rx}"];relation["waterway"="river"]["name:en"~"{rx}"];relation["waterway"="river"]["name"~"{rx}"];);out geom;'
        try:
            n0 = 0
            for nm, en_, inter, ws in river_tile(q): add(fa, en, 0, ws); n0 += 1
            log(f'  رتبه ۰ {fa}: {n0} عنصر')
        except Exception as e: log(f'  ✗ {fa}: {str(e)[:100]}')
        time.sleep(2)
    # ۲) رودهای رتبهٔ ۱ (فهرست کاربر) داخل ایران
    for fa, rx in IR_RIVERS:
        q = f'[out:json][timeout:120];area["ISO3166-1"="IR"]->.a;(way["waterway"="river"]["name"~"{rx}"](area.a);way["waterway"="river"]["name:fa"~"{rx}"](area.a);way["waterway"="river"]["name:en"~"{rx}"](area.a););out geom;'
        try:
            n1 = 0
            for nm, en_, inter, ws in river_tile(q): add(fa, '', 1, ws); n1 += 1
            log(f'  رتبه ۱ {fa}: {n1} عنصر' if n1 else f'  ✗ {fa}: پیدا نشد')
        except Exception as e: log(f'  ✗ {fa}: {str(e)[:100]}')
        time.sleep(2)
    # ۳) سایر رودهای نام‌دار ایران؛ رتبه از روی طول (دائمی: ≥۶۰ کیلومتر → ۲؛ ۲۰ تا ۶۰ → ۳؛ فصلی/مسیل اصلی: ≥۴۰ کیلومتر → ۳)
    for la in range(25, 40, 5):
        for lo in range(44, 64, 5):
            q = f'[out:json][timeout:180][bbox:{la},{lo},{la + 5},{lo + 5}];way["waterway"="river"]["name"];out geom qt;'
            try:
                for nm, en_, inter, ws in river_tile(q):
                    if nm: add(nm, en_, 9, ws, inter)
            except Exception as e: log(f'  ✗ رود {la},{lo}: {str(e)[:80]}')
            time.sleep(3)
    out = []
    for nm, r in res.items():
        uw = {min(tuple(w), tuple(w[::-1])): w for w in r['w'] if len(w) > 1}
        lines = [dp(l, 0.003) for l in chain(list(uw.values())) if len(l) >= 2]
        L = sum(hav(l) for l in lines)
        rk = r['rk']
        if rk == 9:
            if not r['inter'] and L >= 60: rk = 2
            elif not r['inter'] and L >= 20: rk = 3
            elif r['inter'] and L >= 40: rk = 3
            else: continue
        out.append({'n': nm, 'rk': rk, 'len': round(L), 'l': [rnd(l) for l in lines]})
    cap = {2: 90, 3: 260}
    out.sort(key=lambda r: (r['rk'], -r['len'])); keep = []; cnt = {}
    for r in out:
        cnt[r['rk']] = cnt.get(r['rk'], 0) + 1
        if r['rk'] in cap and cnt[r['rk']] > cap[r['rk']]: continue
        keep.append(r)
    log('  رودها بر حسب رتبه:', {k: sum(1 for r in keep if r['rk'] == k) for k in (0, 1, 2, 3)}); return keep

# ---------- جاده‌ها: ۱=آزادراه/بزرگراه، ۲=جادهٔ اصلی ملی (trunk)، ۳=جادهٔ اصلی استانی (primary) ----------
def roads():
    out = []; cells = [(la, lo) for la in range(25, 40, 5) for lo in range(44, 64, 5)]; RK = {'motorway': 1, 'trunk': 2, 'primary': 3}; MINLEN = {1: 3, 2: 6, 3: 15}
    for la, lo in cells:
        q = f'[out:json][timeout:180][bbox:{la},{lo},{la + 5},{lo + 5}];(way["highway"~"^(motorway|trunk|primary)$"];);out geom qt;'
        try: d = overpass(q)
        except Exception as e: log(f'  ✗ جاده {la},{lo}: {str(e)[:80]}'); continue
        ws = {1: [], 2: [], 3: []}
        for el in d.get('elements', []):
            g = geom_of(el)[0]
            if len(g) > 1: ws[RK.get(el.get('tags', {}).get('highway'), 3)].append(g)
        n = 0
        for c, w in ws.items():
            for l in chain(w):
                l = dp(l, 0.006 if c == 1 else 0.01)
                if len(l) >= 2 and hav(l) >= MINLEN[c]: out.append({'c': c, 'l': rnd(l)}); n += 1
        log(f'  جاده {la},{lo}: {n} خط'); time.sleep(3)
    return out

# ---------- مرز کشورها (Natural Earth 10m، دامنهٔ عمومی) برای زوم خاورمیانه ----------
def borders():
    """مرز خشکی کشورها؛ r65: دامنه برای کادر «اروپا» بزرگ شد (۱۶−…۷۲°E، ۴…۶۶°N): داخل خاورمیانه ریز (۰٫۰۰۴°)، بیرون آن درشت‌تر (۰٫۰۲°)."""
    d = json.loads(get('https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_admin_0_boundary_lines_land.geojson'))
    out = []
    for f in d.get('features', []):
        g = f.get('geometry') or {}; ls = g.get('coordinates', []) if g.get('type') == 'MultiLineString' else [g.get('coordinates', [])] if g.get('type') == 'LineString' else []
        for l in ls:
            pts = [(x, y) for x, y in l]
            if not pts or not any(-16 <= x <= 72 and 4 <= y <= 66 for x, y in pts): continue
            inme = any(15 <= x <= 70 and 8 <= y <= 48 for x, y in pts)
            out.append(rnd(dp(pts, 0.004 if inme else 0.02)))
    log(f'  مرز: {len(out)} خط'); return out

ME_BOX = (17.0, 68.0, 9.0, 45.0)     # lon0, lon1, lat0, lat1 — ساحل داخل این کادر از قبل در خود سایت (blob) هست
def coast():
    """ساحل (Natural Earth 10m) برای کادر اروپا: فقط تکه‌های بیرون از کادر خاورمیانه (تا ساحل دوبار کشیده نشود)."""
    d = json.loads(get('https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_coastline.geojson'))
    out = []; inb = lambda x, y: ME_BOX[0] <= x <= ME_BOX[1] and ME_BOX[2] <= y <= ME_BOX[3]
    for f in d.get('features', []):
        g = f.get('geometry') or {}; ls = g.get('coordinates', []) if g.get('type') == 'MultiLineString' else [g.get('coordinates', [])] if g.get('type') == 'LineString' else []
        for l in ls:
            cur = []
            for x, y in l:
                if not (-18 <= x <= 74 and 2 <= y <= 68) or inb(x, y):
                    if len(cur) > 1: out.append(rnd(dp(cur, 0.012)))
                    cur = []
                else: cur.append((x, y))
            if len(cur) > 1: out.append(rnd(dp(cur, 0.012)))
    log(f'  ساحل: {len(out)} خط'); return out

def mock():
    return {'places': [['تهران', 35.69, 51.39, 0, 8700000, 'cap'], ['کرج', 35.84, 50.94, 1, 1600000, 'cty'], ['دماوند', 35.72, 52.07, 1, 40000, 'cty'], ['آبسرد', 35.67, 52.18, 4, 900, 'pl']],
            'lakes': [{'n': 'دریاچه ارومیه', 'en': 'Lake Urmia', 'r': [[[45.2, 37.6], [45.6, 37.9], [45.7, 37.5], [45.4, 37.2], [45.2, 37.6]]]}],
            'rivers': [{'n': 'کارون', 'rk': 0, 'len': 700, 'l': [[[48.9, 31.0], [48.5, 30.6], [48.1, 30.2]]]}, {'n': 'کرج', 'rk': 3, 'len': 50, 'l': [[[51.0, 36.1], [50.9, 35.95], [50.95, 35.8]]]}], 'roads': [{'c': 1, 'l': [[51.4, 35.7], [50.9, 35.8]]}, {'c': 2, 'l': [[51.4, 35.6], [51.0, 35.5]]}, {'c': 3, 'l': [[51.5, 35.9], [51.8, 36.0]]}], 'borders': [[[44.0, 38.0], [46.0, 36.0], [48.0, 30.0]]]}

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--out', default='geo_out'); ap.add_argument('--only', default='places,lakes,rivers,roads,borders,coast')
    ap.add_argument('--mock', action='store_true'); ap.add_argument('--max-villages', type=int, default=9000)
    ap.add_argument('--base', default='', help='r65: geo.json قبلی (فایل یا آدرس)؛ بخش‌هایی که در --only نیستند از آن حفظ می‌شوند')
    a = ap.parse_args(); os.makedirs(a.out, exist_ok=True); G = {}
    if a.base:
        try:
            raw = open(a.base, 'rb').read() if os.path.exists(a.base) else get(a.base)
            B = json.loads(raw); G = {k: v for k, v in B.items() if isinstance(v, list) and k not in a.only.split(',')}
            log(f'  پایه: بخش‌های حفظ‌شده {sorted(G)}')
        except Exception as e: log(f'✗ خواندن --base ناموفق: {type(e).__name__}: {e}'); sys.exit(2)
    if a.mock: G = mock()
    else:
        for k, f in (('places', lambda: places(a.max_villages)), ('lakes', lakes), ('rivers', rivers), ('roads', roads), ('borders', borders), ('coast', coast)):
            if k not in a.only.split(','): continue
            log(f'▶ {k}')
            try: G[k] = f()
            except Exception as e: log(f'✗ {k}: {type(e).__name__}: {e}'); G[k] = []
    G.update(v=1, built=datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%MZ'), src='GeoNames (CC-BY 4.0); © OpenStreetMap contributors (ODbL)')
    p = os.path.join(a.out, 'geo.json'); open(p, 'w', encoding='utf8').write(json.dumps(G, ensure_ascii=False, separators=(',', ':')))
    log(f'✓ {p}: {os.path.getsize(p) / 1024:.0f} KB —', {k: len(v) for k, v in G.items() if isinstance(v, list)})

if __name__ == '__main__': main()

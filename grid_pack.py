#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""«بستهٔ شبکه‌ای» ECMWF برای پنل سینرژی/مقطع/جبهه‌ها — مستقیم از ECMWF Open Data (data.ecmwf.int)، بدون Open-Meteo.
متغیرها (ترازهای فشاری): gh (ارتفاع ژئوپتانسیل؛ در بسته به gpm تبدیل می‌شود = gh/9.80665)، t (K)، u، v (m/s)، q (kg/kg)، r (٪)، d (واگرایی، 1/s)، vo (وردایی نسبی، 1/s)، w (Pa/s)
ترازها: ۱۰۰۰ … ۲۰۰ hPa (پیش‌فرض ۱۰ تراز) روی ۵–۶۵°N و ۱۰–۹۰°E (اروپا، مصر/لیبی، شمال کاسپین، دریای عرب)، شبکهٔ ۰٫۵° (نمونه‌برداری هر ۲ نقطه از ۰٫۲۵°).
خروجی: برای هر گام یک فایل باینری  ec_<run>_<step>.bin  (هدر JSON + int16 فشرده با zlib) و manifest.json؛ آپلود با nwp_upload.php (a=gridput/gridend).
اجرا:  python grid_pack.py --host https://wtafkik.ir/online --key KEY          (روی Actions؛ آخرین اجرای موجود)
       python grid_pack.py --out out_grid --steps 0-72/6                          (ذخیرهٔ محلی)
       python grid_pack.py --mock --out out_grid                                  (آزمون بدون شبکه)"""
import argparse, json, os, struct, sys, time, zlib, datetime as dt
import numpy as np

VARS = ['gh', 't', 'u', 'v', 'q', 'r', 'd', 'vo', 'w']
# مقیاس‌دهی int16:  ذخیره = round((x − off)·sc)   ← x = ذخیره/sc + off
QUANT = {'gh': (0.0, 1.0, 'gpm'), 't': (250.0, 100.0, 'K'), 'u': (0.0, 100.0, 'm/s'), 'v': (0.0, 100.0, 'm/s'), 'q': (0.0, 1e6, 'kg/kg'),
         'r': (0.0, 100.0, '%'), 'd': (0.0, 1e7, '1/s'), 'vo': (0.0, 1e7, '1/s'), 'w': (0.0, 1000.0, 'Pa/s')}
LEVELS = [1000, 925, 850, 700, 600, 500, 400, 300, 250, 200]
BOX = dict(lat0=65.0, lat1=5.0, lon0=10.0, lon1=90.0); DEC = 2          # عرض کاهشی؛ DEC: هر ۲ نقطه (۰٫۵°)
MAGIC = b'MSG1'
def log(*a): print(*a, flush=True)

def lonlat_axes():
    lat = np.arange(BOX['lat0'], BOX['lat1'] - 1e-6, -0.25 * DEC); lon = np.arange(BOX['lon0'], BOX['lon1'] + 1e-6, 0.25 * DEC); return lat, lon

def encode(fields, run, step, valid):
    """fields: dict var → آرایهٔ (nlev, nlat, nlon) با ترتیب ترازها = LEVELS (NaN = نبود) → bytes."""
    lat, lon = lonlat_axes(); arr = np.full((len(VARS), len(LEVELS), len(lat), len(lon)), -32768, np.int16); q = {}
    for i, k in enumerate(VARS):
        off, sc, unit = QUANT[k]; q[k] = {'off': off, 'sc': sc, 'unit': unit}
        if k not in fields: continue
        x = np.asarray(fields[k], float); m = np.isfinite(x); z = np.where(m, np.rint((x - off) * sc), -32768); z = np.clip(z, -32767, 32767); z[~m] = -32768; arr[i] = z.astype(np.int16)
    hd = {'model': 'ecmwf', 'run': run, 'step': int(step), 'valid': valid, 'lat0': float(lat[0]), 'dlat': -0.25 * DEC, 'nlat': len(lat), 'lon0': float(lon[0]), 'dlon': 0.25 * DEC, 'nlon': len(lon), 'levels': LEVELS, 'vars': VARS, 'q': q, 'order': 'var,lev,lat,lon', 'dtype': 'int16le', 'missing': -32768}
    h = json.dumps(hd, ensure_ascii=False).encode('utf-8'); body = zlib.compress(arr.astype('<i2').tobytes(), 6)
    return MAGIC + struct.pack('<I', len(h)) + h + body

def decode(b):
    if b[:4] != MAGIC: raise ValueError('magic')
    n = struct.unpack('<I', b[4:8])[0]; hd = json.loads(b[8:8 + n].decode('utf-8')); raw = np.frombuffer(zlib.decompress(b[8 + n:]), '<i2')
    a = raw.reshape(len(hd['vars']), len(hd['levels']), hd['nlat'], hd['nlon']); out = {}
    for i, k in enumerate(hd['vars']):
        z = a[i].astype(float); m = a[i] == hd['missing']; out[k] = np.where(m, np.nan, z / hd['q'][k]['sc'] + hd['q'][k]['off'])
    return hd, out

# ───── دریافت از ECMWF Open Data ─────
def parse_steps(s):
    if '/' in s: r, st = s.split('/'); a, b = r.split('-'); return list(range(int(a), int(b) + 1, int(st)))
    return [int(x) for x in s.split(',')]
def fetch_run(steps, workdir, run=None):
    """آخرین اجرای موجود (یا run مشخص) را می‌گیرد؛ خروجی: (run datetime, {step: {var: (nlev, nlat, nlon)}})."""
    from ecmwf.opendata import Client
    import eccodes as ec
    cl = Client(source='ecmwf'); base = dict(type='fc', stream='oper', levtype='pl', levelist=LEVELS, param=VARS)
    if run is None:
        run = cl.latest(dict(base, step=max(steps)))
        log('آخرین اجرای دارای گام', max(steps), ':', run)
    tgt = os.path.join(workdir, f'ec_{run:%Y%m%d%H}.grib2'); os.makedirs(workdir, exist_ok=True)
    try: cl.retrieve(dict(base, date=run.strftime('%Y%m%d'), time=run.hour, step=steps), tgt)
    except Exception as e:                       # اگر پارامتری (مثلاً w) در این جریان نبود، بدون پارامترهای اختیاری تلاش دوباره
        log('  ⚠ دریافت کامل شکست خورد:', str(e)[:200], '— تلاش بدون w/d/vo'); cl.retrieve(dict(base, param=[v for v in VARS if v not in ('w', 'd', 'vo')], date=run.strftime('%Y%m%d'), time=run.hour, step=steps), tgt); log('دریافت شد:', os.path.getsize(tgt) // 1048576, 'MB')
    lat, lon = lonlat_axes(); out = {}
    with open(tgt, 'rb') as f:
        while True:
            g = ec.codes_grib_new_from_file(f)
            if g is None: break
            try:
                k = ec.codes_get(g, 'shortName'); lv = ec.codes_get(g, 'level'); st = ec.codes_get(g, 'step')
                if k not in VARS or lv not in LEVELS: continue
                ni, nj = ec.codes_get(g, 'Ni'), ec.codes_get(g, 'Nj'); la0 = ec.codes_get(g, 'latitudeOfFirstGridPointInDegrees'); lo0 = ec.codes_get(g, 'longitudeOfFirstGridPointInDegrees'); di = ec.codes_get(g, 'iDirectionIncrementInDegrees'); dj = ec.codes_get(g, 'jDirectionIncrementInDegrees')
                v = ec.codes_get_values(g).reshape(nj, ni)
                if ec.codes_get(g, 'jScansPositively'): v = v[::-1]; la0 = la0 - dj * (nj - 1)
                la_axis = la0 - dj * np.arange(nj) if not ec.codes_get(g, 'jScansPositively') else la0 + dj * np.arange(nj)[::-1]
                lo_axis = (lo0 + di * np.arange(ni)) % 360
                ia = np.rint((la0 - lat) / dj).astype(int) if not ec.codes_get(g, 'jScansPositively') else np.rint((la0 + dj * (nj - 1) - lat) / dj).astype(int)
                ib = np.rint(((lon - lo0) % 360) / di).astype(int) % ni
                sub = v[np.clip(ia, 0, nj - 1)][:, ib]
                d = out.setdefault(int(st), {}); a = d.setdefault(k, np.full((len(LEVELS), len(lat), len(lon)), np.nan)); a[LEVELS.index(int(lv))] = sub
            finally: ec.codes_release(g)
    for st, d in out.items():      # gh در Open Data = ارتفاع ژئوپتانسیل (gpm)؛ اگر m²/s² بود (۵۰۰ hPa ≈ ۴۹٬۰۰۰) به gpm تبدیل می‌شود
        if 'gh' in d:
            m = np.nanmean(d['gh'][LEVELS.index(500)])
            if m > 20000: d['gh'] = d['gh'] / 9.80665; log('  هشدار: gh به m²/s² بود؛ تبدیل شد')
            if not 4500 < np.nanmean(d['gh'][LEVELS.index(500)]) < 6300: log('  ⚠ ارتفاع ۵۰۰ hPa خارج از بازهٔ معقول:', np.nanmean(d['gh'][LEVELS.index(500)]))
    return run, out

def mock_fields(step):
    """میدان مصنوعی هموار (جت + ناوه + جبهه) برای آزمون قالب و رندر — داده نیست."""
    lat, lon = lonlat_axes(); LA, LO = np.meshgrid(lat, lon, indexing='ij'); f = {}; sh = step * 0.25
    for k in VARS: f[k] = np.zeros((len(LEVELS), len(lat), len(lon)))
    for i, p in enumerate(LEVELS):
        z0 = 9.81 * (-7.0 * np.log(p / 1000.0) * 1000.0 / 1.0 * 1.0 + 0)      # تقریب
        T = 288.0 - 6.5 * (-7.0 * np.log(p / 1000.0)) - 0.35 * (LA - 35.0) + 2.0 * np.sin(np.deg2rad(LO * 6 - sh))
        f['t'][i] = T; f['gh'][i] = (8000.0 * np.log(1000.0 / p) + 40.0 * (LA - 35.0) * -1.0 + 60.0 * np.sin(np.deg2rad(LO * 6 - sh)))
        f['u'][i] = 25.0 * np.exp(-((LA - 38.0) / 10.0) ** 2) * (1000.0 / p) ** -0.3 + 3 * np.sin(np.deg2rad(LO * 6)); f['v'][i] = 8.0 * np.sin(np.deg2rad(LO * 6 - sh)) * np.exp(-((LA - 38.0) / 15.0) ** 2)
        f['r'][i] = np.clip(60 + 35 * np.sin(np.deg2rad(LO * 4 + LA * 2 + sh)), 3, 100); f['q'][i] = 0.004 * (p / 1000.0) ** 2 * f['r'][i] / 60.0
        f['w'][i] = 0.3 * np.sin(np.deg2rad(LO * 6 - sh)) * np.sin(np.deg2rad((p - 200) / 800.0 * 180)); f['d'][i] = 3e-5 * np.sin(np.deg2rad(LO * 6 + 30)); f['vo'][i] = 8e-5 * np.sin(np.deg2rad(LO * 6 - sh)) * np.exp(-((LA - 38.0) / 10.0) ** 2)
    return f

# ───── آپلود به هاست ─────
class Host:
    def __init__(s, host, key): s.host, s.key = host.rstrip('/'), key
    def call(s, a, **kw):
        import requests
        u = f"{s.host}/nwp_upload.php?a={a}&key={requests.utils.quote(s.key)}"
        for k in range(5):
            try:
                r = requests.post(u, timeout=120, **kw)
                if r.status_code == 403: sys.exit('✗ کلید آپلود اشتباه است')
                return r.json()
            except SystemExit: raise
            except Exception as e: log('  … خطای ارتباط:', e); time.sleep(5 * (k + 1))
        return {}

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--host'); ap.add_argument('--key', default=''); ap.add_argument('--out'); ap.add_argument('--steps', default='0-72/6'); ap.add_argument('--run', default='', help='YYYYMMDDHH؛ خالی = آخرین'); ap.add_argument('--mock', action='store_true'); a = ap.parse_args()
    if not a.host and not a.out: sys.exit('--host یا --out لازم است')
    steps = parse_steps(a.steps); H = Host(a.host, a.key) if a.host else None; wd = a.out or '.'
    if a.mock: run = dt.datetime(2026, 10, 21, 0); data = {s: mock_fields(s) for s in steps}
    else: run, data = fetch_run(steps, os.path.join(wd, '_grib'), dt.datetime.strptime(a.run, '%Y%m%d%H') if a.run else None)
    rs = run.strftime('%Y%m%d%H'); man = {'model': 'ecmwf', 'run': rs, 'levels': LEVELS, 'vars': VARS, 'steps': [], 'updated': dt.datetime.utcnow().isoformat(timespec='seconds') + 'Z', 'source': 'ECMWF Open Data (CC-BY-4.0)'}
    for s in sorted(data):
        valid = (run + dt.timedelta(hours=s)).strftime('%Y-%m-%dT%H:00Z'); b = encode(data[s], rs, s, valid); fn = f'ec_{rs}_{s:03d}.bin'
        if a.out: os.makedirs(os.path.join(a.out, rs), exist_ok=True); open(os.path.join(a.out, rs, fn), 'wb').write(b)
        if H: r = H.call('gridput', data={'model': 'ecmwf', 'run': rs, 'file': fn}, files={'bin': (fn, b, 'application/octet-stream')}); log('  آپلود', fn, len(b) // 1024, 'KB', r)
        else: log('  ذخیره', fn, len(b) // 1024, 'KB')
        man['steps'].append({'step': s, 'valid': valid, 'f': fn, 'kb': len(b) // 1024})
    if a.out: json.dump(man, open(os.path.join(a.out, rs, 'manifest.json'), 'w'), ensure_ascii=False)
    if H: log('  پایان:', H.call('gridend', json=man))
if __name__ == '__main__': main()

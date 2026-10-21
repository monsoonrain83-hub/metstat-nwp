#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""«بستهٔ شبکه‌ای» ECMWF برای پنل سینرژی/مقطع/جبهه‌ها — مستقیم از ECMWF Open Data (data.ecmwf.int)، بدون Open-Meteo.
متغیرها (ترازهای فشاری): gh (ارتفاع ژئوپتانسیل؛ در بسته به gpm تبدیل می‌شود = gh/9.80665)، t (K)، u، v (m/s)، q (kg/kg)، r (٪)، d (واگرایی، 1/s)، vo (وردایی نسبی، 1/s)، w (Pa/s)
ترازها: ۱۰۰۰ … ۲۰۰ hPa (پیش‌فرض ۱۰ تراز) روی ۵–۶۵°N و ۱۰–۹۰°E (اروپا، مصر/لیبی، شمال کاسپین، دریای عرب)، شبکهٔ ۰٫۵° (نمونه‌برداری هر ۲ نقطه از ۰٫۲۵°).
خروجی: برای هر گام یک فایل باینری  ec_<run>_<step>.bin  (هدر JSON + int16 فشرده با zlib) و manifest.json؛ آپلود با nwp_upload.php (a=gridput/gridend).
اجرا:  python grid_pack.py --host https://wtafkik.ir/online --key KEY          (روی Actions؛ آخرین اجرای موجود)
       python grid_pack.py --out out_grid --steps 0-72/6                          (ذخیرهٔ محلی)
       python grid_pack.py --mock --out out_grid                                  (آزمون بدون شبکه)"""
import argparse, json, os, re, struct, sys, time, zlib, datetime as dt
import numpy as np

VARS = ['gh', 't', 'u', 'v', 'q', 'r', 'd', 'vo', 'w']
PLV = list(VARS)                          # متغیرهای ترازی (دریافت از ECMWF)
SFC = ['msl', 'sp', 't2', 'd2', 'u10', 'v10']  # r66: سطحی؛ در آرایه فقط در تراز اول (اندیس ۰) می‌نشینند (hPa، K، m/s)
ALLV = VARS + SFC
# مقیاس‌دهی int16:  ذخیره = round((x − off)·sc)   ← x = ذخیره/sc + off
QUANT = {'gh': (0.0, 1.0, 'gpm'), 't': (250.0, 100.0, 'K'), 'u': (0.0, 100.0, 'm/s'), 'v': (0.0, 100.0, 'm/s'), 'q': (0.0, 1e6, 'kg/kg'),
         'r': (0.0, 100.0, '%'), 'd': (0.0, 1e7, '1/s'), 'vo': (0.0, 1e7, '1/s'), 'w': (0.0, 1000.0, 'Pa/s'),
         'msl': (1000.0, 100.0, 'hPa'), 'sp': (800.0, 100.0, 'hPa'), 't2': (250.0, 100.0, 'K'), 'd2': (250.0, 100.0, 'K'), 'u10': (0.0, 100.0, 'm/s'), 'v10': (0.0, 100.0, 'm/s')}
LEVELS = [1000, 925, 850, 700, 600, 500, 400, 300, 250, 200]
BOX = dict(lat0=65.0, lat1=5.0, lon0=10.0, lon1=90.0); DEC = 2          # عرض کاهشی؛ DEC: هر ۲ نقطه (۰٫۵°)
MAGIC = b'MSG1'
def log(*a): print(*a, flush=True)

def lonlat_axes():
    lat = np.arange(BOX['lat0'], BOX['lat1'] - 1e-6, -0.25 * DEC); lon = np.arange(BOX['lon0'], BOX['lon1'] + 1e-6, 0.25 * DEC); return lat, lon

def encode(fields, run, step, valid, model='ecmwf'):
    """fields: dict var → آرایهٔ (nlev, nlat, nlon) با ترتیب ترازها = LEVELS (NaN = نبود) → bytes."""
    lat, lon = lonlat_axes(); arr = np.full((len(ALLV), len(LEVELS), len(lat), len(lon)), -32768, np.int16); q = {}
    for i, k in enumerate(ALLV):
        off, sc, unit = QUANT[k]; q[k] = {'off': off, 'sc': sc, 'unit': unit}
        if k not in fields: continue
        x = np.asarray(fields[k], float); m = np.isfinite(x); z = np.where(m, np.rint((x - off) * sc), -32768); z = np.clip(z, -32767, 32767); z[~m] = -32768
        if k in SFC: arr[i, 0] = z.astype(np.int16)            # سطحی: فقط اندیس تراز ۰
        else: arr[i] = z.astype(np.int16)
    hd = {'model': model, 'run': run, 'step': int(step), 'valid': valid, 'lat0': float(lat[0]), 'dlat': -0.25 * DEC, 'nlat': len(lat), 'lon0': float(lon[0]), 'dlon': 0.25 * DEC, 'nlon': len(lon), 'levels': LEVELS, 'vars': ALLV, 'sfc': SFC, 'q': q, 'order': 'var,lev,lat,lon', 'dtype': 'int16le', 'missing': -32768}
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
    sfc_t = os.path.join(workdir, f'ec_{run:%Y%m%d%H}_sfc.grib2')
    try: cl.retrieve(dict(type='fc', stream='oper', levtype='sfc', param=['msl', 'sp', '2t', '2d', '10u', '10v'], date=run.strftime('%Y%m%d'), time=run.hour, step=steps), sfc_t)
    except Exception as e: log('  ⚠ دریافت سطحی (msl/sp/2t/2d/10u/10v) شکست خورد:', str(e)[:200]); sfc_t = None
    lat, lon = lonlat_axes(); out = {}
    SFCMAP = {'msl': 'msl', 'sp': 'sp', '2t': 't2', '2d': 'd2', '10u': 'u10', '10v': 'v10'}
    for path in [tgt] + ([sfc_t] if sfc_t else []): _read_grib(path, out, lat, lon, ec, SFCMAP)
    return _post(run, out)

def _read_grib(tgt, out, lat, lon, ec, SFCMAP):
    with open(tgt, 'rb') as f:
        while True:
            g = ec.codes_grib_new_from_file(f)
            if g is None: break
            try:
                k = ec.codes_get(g, 'shortName'); lv = ec.codes_get(g, 'level'); st = ec.codes_get(g, 'step')
                if k in SFCMAP:
                    k = SFCMAP[k]; ni, nj = ec.codes_get(g, 'Ni'), ec.codes_get(g, 'Nj'); la0 = ec.codes_get(g, 'latitudeOfFirstGridPointInDegrees'); lo0 = ec.codes_get(g, 'longitudeOfFirstGridPointInDegrees'); di = ec.codes_get(g, 'iDirectionIncrementInDegrees'); dj = ec.codes_get(g, 'jDirectionIncrementInDegrees')
                    v = ec.codes_get_values(g).reshape(nj, ni); ia = np.rint((la0 - lat) / dj).astype(int); ib = np.rint(((lon - lo0) % 360) / di).astype(int) % ni
                    sub = v[np.clip(ia, 0, nj - 1)][:, ib]
                    if k in ('msl', 'sp'): sub = sub / 100.0
                    out.setdefault(int(st), {})[k] = sub; continue
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

def _post(run, out):
    for st, d in out.items():      # gh در Open Data = ارتفاع ژئوپتانسیل (gpm)؛ اگر m²/s² بود (۵۰۰ hPa ≈ ۴۹٬۰۰۰) به gpm تبدیل می‌شود
        if 'gh' in d:
            m = np.nanmean(d['gh'][LEVELS.index(500)])
            if m > 20000: d['gh'] = d['gh'] / 9.80665; log('  هشدار: gh به m²/s² بود؛ تبدیل شد')
            if not 4500 < np.nanmean(d['gh'][LEVELS.index(500)]) < 6300: log('  ⚠ ارتفاع ۵۰۰ hPa خارج از بازهٔ معقول:', np.nanmean(d['gh'][LEVELS.index(500)]))
    return run, out


# ───── GFS 0.25° از s3://noaa-gfs-bdp-pds (دسترسی عمومی؛ خواندن بازه‌ای با .idx) ─────
GFS_URL = 'https://noaa-gfs-bdp-pds.s3.amazonaws.com'
GFS_PL = {'HGT': 'gh', 'TMP': 't', 'UGRD': 'u', 'VGRD': 'v', 'RH': 'r', 'SPFH': 'q', 'VVEL': 'w'}
GFS_SFC = {('PRMSL', 'mean sea level'): 'msl', ('PRES', 'surface'): 'sp', ('TMP', '2 m above ground'): 't2', ('DPT', '2 m above ground'): 'd2', ('UGRD', '10 m above ground'): 'u10', ('VGRD', '10 m above ground'): 'v10'}
def _gfs_path(run, step): return f'gfs.{run:%Y%m%d}/{run:%H}/atmos/gfs.t{run:%H}z.pgrb2.0p25.f{step:03d}'
def _gfs_pick(requests, steps):
    now = dt.datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    base = now - dt.timedelta(hours=now.hour % 6)
    for k in range(0, 8):
        run = base - dt.timedelta(hours=6 * k)
        try:
            r = requests.get(f'{GFS_URL}/{_gfs_path(run, max(steps))}.idx', timeout=30)
            if r.status_code == 200 and len(r.text) > 1000: return run
        except Exception as e: log('  … بررسی GFS', run, e)
    raise SystemExit('✗ اجرای کامل GFS پیدا نشد')
def fetch_gfs(steps, workdir, run=None):
    import requests, eccodes as ec
    from concurrent.futures import ThreadPoolExecutor
    if run is None: run = _gfs_pick(requests, steps); log('آخرین اجرای GFS با گام', max(steps), ':', run)
    lat, lon = lonlat_axes(); ia = np.rint((90.0 - lat) / 0.25).astype(int); ib = np.rint(((lon - 0.0) % 360) / 0.25).astype(int) % 1440; out = {}
    def one(st):
        u = f'{GFS_URL}/{_gfs_path(run, st)}'; txt = requests.get(u + '.idx', timeout=60).text; L_ = [l.split(':') for l in txt.splitlines() if l.strip()]; offs = [int(x[1]) for x in L_]; want = []
        for i, x in enumerate(L_):
            var, lev = x[3], x[4]; end = offs[i + 1] - 1 if i + 1 < len(L_) else ''
            m = re.fullmatch(r'(\d+) mb', lev)
            if var in GFS_PL and m and int(m.group(1)) in LEVELS: want.append((GFS_PL[var], int(m.group(1)), offs[i], end))
            elif (var, lev) in GFS_SFC: want.append((GFS_SFC[(var, lev)], 0, offs[i], end))
        d = {}
        for k, lv, a, b in want:
            for tr in range(3):
                try:
                    r = requests.get(u, headers={'Range': f'bytes={a}-{b}'}, timeout=120); r.raise_for_status(); break
                except Exception as e:
                    if tr == 2: raise
                    time.sleep(3)
            g = ec.codes_new_from_message(r.content)
            try:
                ni, nj = ec.codes_get(g, 'Ni'), ec.codes_get(g, 'Nj'); v = ec.codes_get_values(g).reshape(nj, ni)
                if ec.codes_get(g, 'jScansPositively'): v = v[::-1]
                sub = v[np.clip(ia, 0, nj - 1)][:, ib]
            finally: ec.codes_release(g)
            if k in SFC:
                if k in ('msl', 'sp'): sub = sub / 100.0
                d[k] = sub
            else: d.setdefault(k, np.full((len(LEVELS), len(lat), len(lon)), np.nan))[LEVELS.index(lv)] = sub
        log('  GFS گام', st, ':', len(want), 'پیام'); return st, d
    with ThreadPoolExecutor(3) as ex:
        for st, d in ex.map(one, steps): out[st] = d
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
    f['msl'] = 1013.0 + 8 * np.sin(np.deg2rad(LO * 4 - sh)) - 0.2 * (LA - 35.0); f['sp'] = 1013.0 * np.exp(-np.maximum(0, 800 * np.sin(np.deg2rad((LO - 45) * 3)) ** 2 * (np.abs(LA - 33) < 8)) / 8000.0); f['t2'] = f['t'][0] - 1.0; f['d2'] = f['t'][0] - 8.0; f['u10'] = f['u'][0] * 0.4; f['v10'] = f['v'][0] * 0.4
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
    ap = argparse.ArgumentParser(); ap.add_argument('--host'); ap.add_argument('--key', default=''); ap.add_argument('--out'); ap.add_argument('--steps', default='0-72/6'); ap.add_argument('--run', default='', help='YYYYMMDDHH؛ خالی = آخرین'); ap.add_argument('--mock', action='store_true'); ap.add_argument('--model', default='ecmwf', choices=['ecmwf', 'gfs']); a = ap.parse_args()
    if not a.host and not a.out: sys.exit('--host یا --out لازم است')
    steps = parse_steps(a.steps); H = Host(a.host, a.key) if a.host else None; wd = a.out or '.'
    if a.mock: run = dt.datetime(2026, 10, 21, 0); data = {s: mock_fields(s) for s in steps}
    else:
        fr = dt.datetime.strptime(a.run, '%Y%m%d%H') if a.run else None
        run, data = (fetch_gfs if a.model == 'gfs' else fetch_run)(steps, os.path.join(wd, '_grib'), fr)
    pre = 'gfs' if a.model == 'gfs' else 'ec'; src = 'NOAA GFS 0.25° (NOMADS/AWS Open Data، دامنهٔ عمومی)' if a.model == 'gfs' else 'ECMWF Open Data (CC-BY-4.0)'
    rs = run.strftime('%Y%m%d%H'); man = {'model': a.model, 'run': rs, 'levels': LEVELS, 'vars': ALLV, 'sfc': SFC, 'steps': [], 'updated': dt.datetime.utcnow().isoformat(timespec='seconds') + 'Z', 'source': src}
    for s in sorted(data):
        valid = (run + dt.timedelta(hours=s)).strftime('%Y-%m-%dT%H:00Z'); b = encode(data[s], rs, s, valid, a.model); fn = f'{pre}_{rs}_{s:03d}.bin'
        if a.out: os.makedirs(os.path.join(a.out, rs), exist_ok=True); open(os.path.join(a.out, rs, fn), 'wb').write(b)
        if H: r = H.call('gridput', data={'model': a.model, 'run': rs, 'file': fn}, files={'bin': (fn, b, 'application/octet-stream')}); log('  آپلود', fn, len(b) // 1024, 'KB', r)
        else: log('  ذخیره', fn, len(b) // 1024, 'KB')
        man['steps'].append({'step': s, 'valid': valid, 'f': fn, 'kb': len(b) // 1024})
    if a.out: json.dump(man, open(os.path.join(a.out, rs, 'manifest.json'), 'w'), ensure_ascii=False)
    if H: log('  پایان:', H.call('gridend', json=man))
if __name__ == '__main__': main()

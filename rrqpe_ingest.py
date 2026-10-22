# -*- coding: utf-8 -*-
"""MetStat — ورود بارش ماهواره‌ای NOAA RRQPE (Enterprise Rain Rate GLB-5) برای خاورمیانه.

منبع: باکت عمومی و ناشناس noaa-enterprise-rainrate-pds (NOAA Open Data، بدون کلید و بدون احراز هویت)
  BLEND/RainRate-Blend-INST/{YYYY}/{MM}/{DD}/{HH}/RRQPE-INST-GLB-5_v1r1_blend_s{YYYYMMDDHHMMSSmmm}_e..._c....nc
  شبکهٔ ۰٫۰۲° ، ۶۵۰۱×۱۸۰۰۰ ، lat = 70 - 0.02*row ، lon = -180 + 0.02*col ؛ متغیر RRQPE (mm/h, scale 0.1) و DQF (۳ = بدون داده)
ساختار فایل‌ها از مستندات ریپوی LibreWXR (AGPL) خوانده شد؛ هیچ کدی از آن کپی نشده است (فقط قالب عمومی داده).

خروجی (پوشهٔ --out):
  manifest.json                        {bounds, frames:[{t, file, fc}], levels, source}
  rr_YYYYMMDDHHMM.png                  فریم مشاهده‌ای (وب‌مرکاتور، رنگ گسسته، شفاف بیرون از بارش)
  nc_YYYYMMDDHHMM.png                  فریم پیش‌بینی ۱۰…۶۰ دقیقه (برون‌یابی حرکت pySTEPS Lucas-Kanade)، اگر pysteps نصب باشد
اجرا:  python3 rrqpe_ingest.py --out site/rrqpe --frames 12
نیاز: numpy, pillow, netCDF4 (یا h5py)؛ اختیاری: pysteps, opencv-python
"""
import argparse, json, math, os, re, sys, tempfile, urllib.request, urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
import numpy as np
from PIL import Image

BUCKET = 'https://noaa-enterprise-rainrate-pds.s3.amazonaws.com'
PREFIX = 'BLEND/RainRate-Blend-INST'
LAT0, RES = 70.0, 0.02
BOX = dict(lon0=25.0, lon1=80.0, lat0=10.0, lat1=60.0)      # خاورمیانه و آسیای غربی/مرکزی
OUT_W = 1100                                               # عرض خروجی (۰٫۰۵° در هر پیکسل)
# رده‌های گسسته (mm/h) و رنگ‌ها — بدون هم‌آمیزی رنگ
LEVELS = [0.1, 0.5, 1, 2, 4, 8, 16, 32, 64]
COLORS = ['#9ad0ff', '#4aa3ff', '#1f6fe0', '#22b14c', '#f2e600', '#ff9a00', '#ff3b30', '#b3009e', '#5b0a6e']


def _hex(c): return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))


def merc_y(lat): return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def http(url, timeout=60):
    with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'MetStat-rrqpe/1.0'}), timeout=timeout) as r:
        return r.read()


def list_hour(dt):
    q = urllib.parse.urlencode({'list-type': '2', 'prefix': f'{PREFIX}/{dt:%Y/%m/%d/%H}/'})
    root = ET.fromstring(http(f'{BUCKET}/?{q}'))
    ns = {'s': root.tag.split('}')[0].strip('{')}
    return [k.text for k in root.findall('.//s:Key', ns) if 'GLB-5' in k.text]


def key_time(key):
    m = re.search(r'_s(\d{14})', key)
    return datetime.strptime(m.group(1), '%Y%m%d%H%M%S').replace(tzinfo=timezone.utc) if m else None


def newest_keys(n, now=None):
    """n اسکن آخر (هر ۱۰ دقیقه) — از ساعت جاری به عقب می‌رود."""
    now = now or datetime.now(timezone.utc); keys = []
    for h in range(0, n // 6 + 4):
        try: keys += list_hour(now - timedelta(hours=h))
        except Exception as e: print('list fail', h, e, file=sys.stderr)
        if len(keys) >= n + 2: break
    keys = sorted({k: key_time(k) for k in keys}.items(), key=lambda kv: kv[1])
    return keys[-n:]


def read_crop(path):
    """RRQPE (mm/h) برش خاورمیانه روی شبکهٔ ۰٫۰۲°؛ نبود داده → NaN. خروجی: آرایه (ردیف شمالی اول)."""
    r0 = int(round((LAT0 - BOX['lat1']) / RES)); r1 = int(round((LAT0 - BOX['lat0']) / RES))
    c0 = int(round((BOX['lon0'] + 180) / RES)); c1 = int(round((BOX['lon1'] + 180) / RES))
    try:
        import netCDF4
        ds = netCDF4.Dataset(path); ds.set_auto_maskandscale(False)
        v = ds.variables['RRQPE'][r0:r1, c0:c1].astype('float32'); q = ds.variables['DQF'][r0:r1, c0:c1]
        sc = float(getattr(ds.variables['RRQPE'], 'scale_factor', 0.1)); ds.close()
    except ImportError:
        import h5py
        with h5py.File(path, 'r') as f:
            v = f['RRQPE'][r0:r1, c0:c1].astype('float32'); q = f['DQF'][r0:r1, c0:c1]
            sc = float(np.atleast_1d(f['RRQPE'].attrs.get('scale_factor', 0.1))[0])
    a = np.where((v <= -9000) | (q == 3), np.nan, v * sc).astype('float32')
    return np.where(a < 0, 0, a)


def to_mercator(a):
    """از شبکهٔ lat/lon به شبکهٔ وب‌مرکاتور (نزدیک‌ترین همسایه — بدون هم‌آمیزی رنگ). a: (ردیف شمالی اول)."""
    h_src, w_src = a.shape
    y0, y1 = merc_y(BOX['lat0']), merc_y(BOX['lat1'])
    H = int(round(OUT_W * (y1 - y0) / math.radians(BOX['lon1'] - BOX['lon0'])))
    ys = y1 - (np.arange(H) + .5) / H * (y1 - y0)                 # از شمال
    lat = np.degrees(2 * np.arctan(np.exp(ys)) - math.pi / 2)
    rows = np.clip(((BOX['lat1'] - lat) / RES).astype(int), 0, h_src - 1)
    cols = np.clip((((np.arange(OUT_W) + .5) / OUT_W * (BOX['lon1'] - BOX['lon0'])) / RES).astype(int), 0, w_src - 1)
    return a[np.ix_(rows, cols)]


def colorize(a):
    rgba = np.zeros(a.shape + (4,), 'uint8'); idx = np.digitize(np.nan_to_num(a, nan=0), LEVELS)   # 0 = زیر آستانه
    for i, c in enumerate(COLORS, 1):
        m = idx == i
        rgba[m] = _hex(c) + (225,)
    rgba[idx > len(COLORS)] = _hex(COLORS[-1]) + (225,)
    rgba[np.isnan(a)] = 0
    return rgba


def _to_db(x):
    d = 10 * np.log10(np.where(np.isfinite(x) & (x >= 0.1), x, np.nan)); return np.where(np.isfinite(d), d, -15.0).astype('float32')


def nowcast(frames, steps=6):
    """frames: فهرست آرایه‌های mm/h (قدیمی→جدید، گام ۱۰ دقیقه). خروجی: steps آرایهٔ پیش‌بینی (برون‌یابی حرکت، بدون ایجاد/نابودی بارش).
    اگر pysteps نصب باشد از Lucas-Kanade آن (BSD-3) استفاده می‌شود؛ وگرنه جریان نوری Farneback در OpenCV (جایگزین)."""
    if len(frames) < 2: return []
    db = np.stack([_to_db(f) for f in frames[-3:]]); out = None
    try:
        from pysteps import motion, nowcasts
        V = motion.get_method('LK')(db); out = nowcasts.get_method('extrapolation')(db[-1], V, steps)
    except Exception:
        try:
            import cv2
            g = lambda d: np.clip((d + 15) / 50 * 255, 0, 255).astype('uint8')
            fl = cv2.calcOpticalFlowFarneback(g(db[-2]), g(db[-1]), None, 0.5, 4, 25, 3, 7, 1.5, 0)   # حرکت از فریم قبل به فریم آخر (px/گام)
            h, w = db[-1].shape; gx, gy = np.meshgrid(np.arange(w, dtype='float32'), np.arange(h, dtype='float32'))
            out = []
            for k in range(1, steps + 1):                                                                # پس‌نگر: مقدار در x-k·v
                out.append(cv2.remap(db[-1], gx - k * fl[..., 0], gy - k * fl[..., 1], cv2.INTER_NEAREST, borderValue=-15.0))
        except Exception as e:
            print('nowcast unavailable:', e, file=sys.stderr); return []
    r = [np.where(o > -14, 10 ** (o / 10), 0).astype('float32') for o in out]
    for x in r: x[x < 0.1] = 0
    return r


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--out', required=True); ap.add_argument('--frames', type=int, default=12)
    ap.add_argument('--steps', type=int, default=6); ap.add_argument('--host'); ap.add_argument('--key', default=''); a = ap.parse_args(); os.makedirs(a.out, exist_ok=True)
    arrs, times = [], []
    with tempfile.TemporaryDirectory() as td:
        for k, t in newest_keys(a.frames):
            p = os.path.join(td, 'x.nc')
            try: open(p, 'wb').write(http(f'{BUCKET}/{urllib.parse.quote(k)}', timeout=180)); arrs.append(read_crop(p)); times.append(t)
            except Exception as e: print('skip', k, e, file=sys.stderr)
    if not arrs: sys.exit('no frames')
    fr = []
    for ar, t in zip(arrs, times):
        fn = f'rr_{t:%Y%m%d%H%M}.png'; Image.fromarray(colorize(to_mercator(ar))).save(os.path.join(a.out, fn), optimize=True)
        fr.append(dict(t=t.isoformat(), file=fn, fc=0))
    # پیش‌بینی روی شبکهٔ ۰٫۰۴° (۲×۲ میانگین) برای سرعت، سپس تکرار به ۰٫۰۲°
    small = [np.nanmean(np.nan_to_num(x, nan=0).reshape(x.shape[0] // 2, 2, x.shape[1] // 2, 2), axis=(1, 3)) for x in arrs[-3:]] if len(arrs) >= 3 else []
    for i, f in enumerate(nowcast(small, a.steps), 1):
        t = times[-1] + timedelta(minutes=10 * i); big = np.kron(f, np.ones((2, 2), 'float32'))
        fn = f'nc_{t:%Y%m%d%H%M}.png'; Image.fromarray(colorize(to_mercator(big))).save(os.path.join(a.out, fn), optimize=True)
        fr.append(dict(t=t.isoformat(), file=fn, fc=1))
    keep = {f['file'] for f in fr}
    for f in os.listdir(a.out):
        if f.endswith('.png') and f not in keep: os.remove(os.path.join(a.out, f))
    json.dump(dict(bounds=BOX, levels=LEVELS, colors=COLORS, frames=fr, updated=datetime.now(timezone.utc).isoformat(),
                   source='NOAA Enterprise Rain Rate (RRQPE GLB-5) — satellite-derived rain rate; nowcast: pySTEPS Lucas-Kanade extrapolation'),
              open(os.path.join(a.out, 'manifest.json'), 'w'), ensure_ascii=False, indent=1)
    print('frames', len(fr))
    if a.host:                                               # آپلود روی هاست با همان nwp_upload.php (کلید MX_KEY)
        import requests
        base = f"{a.host.rstrip('/')}/nwp_upload.php"; q = {'key': a.key}
        have = set()
        for f in fr:
            for k in range(3):
                try:
                    with open(os.path.join(a.out, f['file']), 'rb') as fh:
                        r = requests.post(base, params=dict(q, a='rrput'), data={'file': f['file']}, files={'png': (f['file'], fh.read(), 'image/png')}, timeout=60)
                    if r.status_code == 403: sys.exit('کلید آپلود اشتباه است (MX_KEY)')
                    if r.json().get('ok'): have.add(f['file']); break
                except SystemExit: raise
                except Exception as e: print('upload retry', f['file'], e, file=sys.stderr)
        fr2 = [f for f in fr if f['file'] in have]
        man = json.load(open(os.path.join(a.out, 'manifest.json'))); man['frames'] = fr2
        r = requests.post(base, params=dict(q, a='rrend'), json=man, timeout=60); print('upload', len(fr2), 'of', len(fr), r.status_code, r.text[:100])
        if not fr2: sys.exit('هیچ فریمی آپلود نشد')


if __name__ == '__main__': main()

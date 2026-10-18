# -*- coding: utf-8 -*-
"""id_points.py — «شناسایی مقدار» فقط روی نقاط مهم: مراکز استان و شهرستان (۴۸۴) + نقاط مهم روستایی/شهرکی (سطح ۳ در geo.json، با سقف).
به‌جای کاشی مقدار کامل (۳۶۰×۲۴۰)، برای هر نقشه یک تصویر WebP بدون‌اتلاف بسیار کوچک ساخته می‌شود: پیکسل ۰ = سرایند (crc۱۶ فهرست نقاط)،
پیکسل ۱ = تعداد نقاط، سپس هر نقطه یک پیکسل با مقدار = (R*256+G)/10 − ۱۰۰ (۰ = بدون داده). سایت همین فهرست را با همین قاعده می‌سازد و crc را مطابقت می‌دهد؛
ناهمخوانی ⇒ سایت فقط بازهٔ طبقهٔ رنگی را نشان می‌دهد (هرگز عدد غلط). قاعدهٔ فهرست (باید با met سایت یکی باشد، 49/51 JS):
  ۱) مراکز (id_seats.json) به ترتیب؛ ۲) از geo.json: places با level==3 در جعبهٔ ایران، به ترتیب (−pop، شمارهٔ ردیف)، حداکثر RURAL_MAX، و فقط اگر
  از هر نقطهٔ قبلی بیش از ۰٫۰۳ درجه (فاصلهٔ ماکسیمم محورها) فاصله داشته باشد."""
import io, json, os
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
BOX = (20.0, 65.0, 12.0, 42.0)          # lon0, lon1, lat0, lat1 کاشی «خاورمیانه»
PXD = 32
IRAN = (25.0, 40.0, 44.0, 63.5)         # lat0, lat1, lon0, lon1
RURAL_MAX = 800
MIN_SEP = 0.03
WIDTH = 64

def load_seats(path=None):
    return json.load(open(path or os.path.join(HERE, 'id_seats.json'), encoding='utf8'))

def fetch_places(host, timeout=60):
    import requests
    r = requests.get(f"{host.rstrip('/')}/data/geo.json", timeout=timeout); r.raise_for_status()
    return r.json().get('places') or []

def build(seats, places):
    """→ [(lat, lon, name), ...]؛ مراکز اول، سپس نقاط مهم روستایی."""
    pts = [(float(s[1]), float(s[2]), s[0]) for s in seats]
    cand = []
    for i, p in enumerate(places or []):
        try:
            if int(p[3]) != 3: continue
            la, lo, pop = float(p[1]), float(p[2]), float(p[4])
        except Exception: continue
        if not (IRAN[0] <= la <= IRAN[1] and IRAN[2] <= lo <= IRAN[3]): continue
        cand.append((-pop, i, la, lo, p[0]))
    cand.sort(key=lambda c: (c[0], c[1]))
    n = 0
    for _, _, la, lo, nm in cand:
        if n >= RURAL_MAX: break
        if any(abs(la - q[0]) <= MIN_SEP and abs(lo - q[1]) <= MIN_SEP for q in pts): continue
        pts.append((la, lo, nm)); n += 1
    return pts

def crc16(pts):
    s = ';'.join('%d,%d' % (int(la * 1000 + 0.5) if la >= 0 else -int(-la * 1000 + 0.5), int(lo * 1000 + 0.5) if lo >= 0 else -int(-lo * 1000 + 0.5)) for la, lo, _ in pts).encode('ascii')
    c = 0xFFFF
    for b in s:
        c ^= b << 8
        for _ in range(8): c = ((c << 1) ^ 0x1021) & 0xFFFF if c & 0x8000 else (c << 1) & 0xFFFF
    return c

def sample(field, pts):
    """مقدار میدان (۹۶۰×۱۴۴۰، شمال بالا) در پیکسل هر نقطه؛ NaN → nan."""
    f = np.asarray(field, dtype=np.float64); H, W = f.shape; out = np.full(len(pts), np.nan)
    for i, (la, lo, _) in enumerate(pts):
        x, y = int(np.floor((lo - BOX[0]) * PXD)), int(np.floor((BOX[3] - la) * PXD))
        if 0 <= x < W and 0 <= y < H: out[i] = f[y, x]
    return out

def encode(field, pts, crc=None):
    vals = sample(field, pts); crc = crc16(pts) if crc is None else crc; n = len(pts)
    q = np.where(np.isfinite(vals), np.clip(np.round((vals + 100.0) * 10.0), 1, 65535), 0).astype(np.uint32)
    flat = np.zeros(n + 2, np.uint32); flat[2:] = q
    h = (n + 2 + WIDTH - 1) // WIDTH; a = np.zeros((h * WIDTH, 3), np.uint8)
    a[2:n + 2, 0] = q >> 8; a[2:n + 2, 1] = q & 255
    a[0] = (crc >> 8, crc & 255, 7); a[1] = (n >> 8, n & 255, 0)
    b = io.BytesIO(); Image.fromarray(a.reshape(h, WIDTH, 3), 'RGB').save(b, 'WEBP', lossless=True, quality=100, method=4); return b.getvalue()

def decode(webp):
    im = np.asarray(Image.open(io.BytesIO(webp)).convert('RGB')).reshape(-1, 3).astype(np.int64)
    crc = int(im[0, 0]) * 256 + int(im[0, 1]); n = int(im[1, 0]) * 256 + int(im[1, 1])
    v = im[2:n + 2, 0] * 256 + im[2:n + 2, 1]
    return crc, n, np.where(v > 0, v / 10.0 - 100.0, np.nan)

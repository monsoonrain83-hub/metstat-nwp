"""مراکز فشار/ارتفاع (L و H) برای کاشی‌های «خاورمیانه» — لایهٔ شفاف جدا (WebP بدون اتلاف) که سایت با تیک روشن/خاموش می‌کند.

روش (طراحی من؛ آستانه‌ها در ثابت‌های بالای فایل‌اند و قابل تنظیم):
  ۱) میدان روی شبکهٔ کاشی (PXD پیکسل/درجه) با DEC کاهش وضوح و با فیلتر گاوسی (SIG درجه) هموار می‌شود — فقط برای یافتن مرکز، نه برای رنگ نقشه.
  ۲) کمینه/بیشینهٔ محلی در پنجرهٔ مربعی به شعاع RAD درجه.
  ۳) «برجستگی» = اختلاف مقدار مرکز با میانگین حلقهٔ شعاع RING درجه (۱۶ نقطه) ≥ آستانهٔ هر متغیر؛ مراکز ضعیف/نویزی حذف می‌شوند.
  ۴) حاشیهٔ MARG درجه از لبهٔ کاشی کنار گذاشته می‌شود (مرکز ناقص/نامطمئن).
  ۵) ترازهای فشاری (۸۵۰/۷۰۰): جایی که فشار سطح کمتر از تراز+PS_MARGIN هکتوپاسکال است (تراز زیر زمین) مرکز ساخته نمی‌شود — میدان آن‌جا برون‌یابی‌شده است.
  ۶) حذف هم‌پوشانی: مراکز هم‌نوع نزدیک‌تر از RAD درجه؛ قوی‌تر می‌ماند.
"""
import io
import numpy as np
from scipy.ndimage import gaussian_filter, minimum_filter, maximum_filter
from PIL import Image, ImageDraw, ImageFont

PXD = 32                    # پیکسل بر درجه (همان nwp_maps.PXD)
DEC = 4                     # کاهش وضوح برای جست‌وجو
RAD = 4.0                   # درجه
RING = 4.0
SIG = 0.5
MARG = 1.5
PS_MARGIN = 15.0            # hPa
# آستانهٔ برجستگی به واحد میدان: فشار سطح دریا hPa؛ ارتفاع ژئوپتانسیل به دکامتر (gpdm)
THR = {'msl': 2.0, 850: 2.0, 700: 3.0, 500: 4.0}
COL = {'L': (214, 32, 28, 255), 'H': (31, 79, 216, 255)}

def find_centers(f, kind, ps=None, pxd=PXD):
    """f: آرایهٔ (ارتفاع، عرض) روی کاشی (NaN مجاز). kind: 'msl'|850|700|500. ps: فشار سطح (hPa) هم‌شکل f یا None.
    خروجی: فهرست (نوع 'L'|'H'، x، y در پیکسل کاشی، مقدار، برجستگی)."""
    f = np.asarray(f, np.float32)
    if not np.isfinite(f).any(): return []
    fill = float(np.nanmean(f)); g = np.nan_to_num(f, nan=fill)
    g = g[::DEC, ::DEC]; p = pxd / DEC
    g = gaussian_filter(g, SIG * p); h, w = g.shape
    r = max(1, int(round(RAD * p))); win = 2 * r + 1; thr = THR[kind]
    mn = minimum_filter(g, size=win, mode='nearest'); mx = maximum_filter(g, size=win, mode='nearest')
    cand = [('L', y, x) for y, x in zip(*np.nonzero(g == mn))] + [('H', y, x) for y, x in zip(*np.nonzero(g == mx))]
    ang = np.linspace(0, 2 * np.pi, 16, endpoint=False); rr = RING * p; mg = MARG * p
    out = []
    for t, y, x in cand:
        if not (mg <= x < w - mg and mg <= y < h - mg): continue
        ys = np.clip(np.round(y + rr * np.sin(ang)).astype(int), 0, h - 1); xs = np.clip(np.round(x + rr * np.cos(ang)).astype(int), 0, w - 1)
        ring = float(g[ys, xs].mean()); v = float(g[y, x]); prom = (ring - v) if t == 'L' else (v - ring)
        if prom < thr: continue
        if ps is not None and isinstance(kind, int):
            pv = np.asarray(ps)[min(ps.shape[0] - 1, y * DEC), min(ps.shape[1] - 1, x * DEC)]
            if not np.isfinite(pv) or pv < kind + PS_MARGIN: continue
        out.append((t, (x + 0.5) * DEC, (y + 0.5) * DEC, v, prom))
    out.sort(key=lambda o: -o[4]); keep = []
    for o in out:
        if all(not (k[0] == o[0] and np.hypot(k[1] - o[1], k[2] - o[2]) < RAD * pxd) for k in keep): keep.append(o)
    return keep

_FONT = {}
def _font(sz):
    if sz not in _FONT:
        for fp in ('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 'DejaVuSans-Bold.ttf'):
            try: _FONT[sz] = ImageFont.truetype(fp, sz); break
            except Exception: pass
        else:
            try:
                import matplotlib, os
                _FONT[sz] = ImageFont.truetype(os.path.join(matplotlib.get_data_path(), 'fonts/ttf/DejaVuSans-Bold.ttf'), sz)
            except Exception: _FONT[sz] = ImageFont.load_default()
    return _FONT[sz]

def encode_layer(centers, W, H, fmt='%d', scale=1.0):
    """لایهٔ شفاف WebP بدون اتلاف؛ None اگر مرکزی نیست. حرف با هالهٔ سفید برای خوانایی روی هر رنگ."""
    if not centers: return None
    im = Image.new('RGBA', (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    fl, fv = _font(int(34 * scale)), _font(int(18 * scale)); halo = (255, 255, 255, 255)
    for t, x, y, v, _ in centers:
        c = COL[t]
        d.text((x, y - 8 * scale), t, font=fl, fill=c, anchor='mm', stroke_width=max(2, int(3 * scale)), stroke_fill=halo)
        d.text((x, y + 18 * scale), fmt % round(v), font=fv, fill=c, anchor='mm', stroke_width=max(2, int(3 * scale)), stroke_fill=halo)
    b = io.BytesIO(); im.save(b, 'WEBP', lossless=True, quality=100, method=4); return b.getvalue()

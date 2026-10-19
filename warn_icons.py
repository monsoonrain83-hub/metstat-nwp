# -*- coding: utf-8 -*-
"""آیکن نوع هشدار روی نقشهٔ «هشدار جوی ترکیبی»: آیکن سفید سه‌بعدی (سایه + لبهٔ تیره + شیب روشنایی) روی هر ناحیهٔ دارای رنگ هشدار.
جای آیکن‌ها طوری انتخاب می‌شود که کل جعبهٔ آیکن داخل ناحیهٔ هشدار باشد و روی مرز/نام‌های لایهٔ overlay نیفتد."""
import math
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

S = 30                      # اندازهٔ آیکن (پیکسل)
ICON_MIN = 2                # r57: آیکن فقط از سطح «زرد» (۲) به بالا؛ سطح ۱ (زرد کم‌رنگ، بارش کم) آیکن ندارد
SS = 4                      # ابرنمونه‌برداری
# ترتیب اولویت وقتی چند خطر هم‌سطح‌اند (مهم‌ترین اول)
PRI = ['wflood', 'whail', 'wtstm', 'wltg', 'wwind', 'wsnow', 'wice', 'wrain', 'wrainl', 'wlog', 'wdust', 'wfog', 'wfrost', 'wgfrost', 'wcold', 'wheat', 'whum']
KIND = dict(wflood='flood', wlog='flood', whail='hail', wtstm='ts', wltg='bolt', wwind='wind', wsnow='snow', wice='cold', wrain='rain', wrainl='rain', wdust='dust', wfog='fog',
            wfrost='cold', wgfrost='cold', wcold='cold', wheat='heat', whum='drop')

def _glyph(d, kind, u):
    """رسم شکل روی ماسک (d=ImageDraw روی 'L'، u=پیکسل به ازای هر واحد از شبکهٔ ۲۴×۲۴)."""
    P = lambda x, y: (x * u, y * u)
    def circ(x, y, r): d.ellipse([(x - r) * u, (y - r) * u, (x + r) * u, (y + r) * u], fill=255)
    def line(pts, w=2.2): d.line([P(*p) for p in pts], fill=255, width=int(w * u), joint='curve'); [circ(p[0], p[1], w / 2) for p in (pts[0], pts[-1])]
    def cloud(dy=0):
        circ(8.5, 9 + dy, 3.8); circ(13, 7.2 + dy, 4.8); circ(17.2, 9.8 + dy, 3.4); d.rounded_rectangle([P(5.5, 9 + dy), P(20.4, 13 + dy)], radius=2 * u, fill=255)
    def bolt(x=0, y=0, s=1.0):
        pts = [(12.8, 2.5), (6.5, 13), (10.8, 13), (8.8, 21.5), (17.5, 10), (13, 10), (15.6, 2.5)]
        d.polygon([P(x + (px - 12) * s + 12, y + (py - 12) * s + 12) for px, py in pts], fill=255)
    if kind == 'ts':
        cloud(-2); d.polygon([P(12.8, 11), P(8.4, 18), (11.2 * u, 18 * u), P(9.6, 23), P(16, 15), P(12.8, 15), P(14.8, 11)], fill=255)
    elif kind == 'bolt': bolt(0, 0, 1.05)
    elif kind == 'rain':
        cloud(-3)
        for x, y in ((8, 14.5), (12.5, 16), (17, 14.5), (10, 19.5), (14.5, 20.5)): line([(x + 0.9, y - 1.4), (x - 0.7, y + 1.6)], 1.9)
    elif kind == 'snow':
        cloud(-3)
        for x, y in ((8, 15.5), (12.5, 17.5), (17, 15.5), (10, 20.5), (15, 21)): circ(x, y, 1.4)
    elif kind == 'hail':
        cloud(-3)
        for x, y in ((8.5, 16.5), (13, 17.8), (17, 16.2), (10.8, 21), (15.6, 21.2)): circ(x, y, 1.9)
    elif kind == 'wind':
        line([(3, 8), (14, 8), (16.5, 7), (16.6, 4.6), (14.6, 4), (13.4, 5.2)]); line([(3, 12.5), (19, 12.5), (21.3, 13.6), (21.2, 16), (19, 16.6), (17.8, 15.4)]); line([(3, 17), (11, 17), (13, 18), (13, 20), (11, 20.4)])
    elif kind == 'flood':
        for y0 in (9, 14, 19): line([(2.5 + i * 3, y0 + (1 if i % 2 else -1)) for i in range(7)], 2.2)
    elif kind == 'fog':
        for y, a, b in ((7, 4, 20), (11.5, 2.5, 17), (16, 6, 21.5), (20.5, 3.5, 18)): line([(a, y), (b, y)], 2.4)
    elif kind == 'dust':
        line([(3, 9), (13, 9), (16, 7.5), (16, 5), (14, 4.4)]); line([(3, 14), (18, 14), (21, 15.5), (20.6, 18), (18.5, 18.4)])
        for x, y in ((6, 19.5), (10, 20.5), (14, 21.5), (18.5, 10.5), (8, 4.8)): circ(x, y, 1.3)
    elif kind == 'heat':
        circ(12, 12, 4.7)
        for k in range(8): a = k * math.pi / 4; line([(12 + math.cos(a) * 7.3, 12 + math.sin(a) * 7.3), (12 + math.cos(a) * 10.2, 12 + math.sin(a) * 10.2)], 1.9)
    elif kind == 'drop':
        circ(12, 15, 6); d.polygon([P(12, 2.5), P(6.6, 12.5), P(17.4, 12.5)], fill=255)
    else:   # cold: دانه‌برف
        R = 9.5
        for k in range(3): a = k * math.pi / 3; line([(12 - math.cos(a) * R, 12 - math.sin(a) * R), (12 + math.cos(a) * R, 12 + math.sin(a) * R)], 2.0)
        for k in range(6):
            a = k * math.pi / 3; x, y = 12 + math.cos(a) * R * .62, 12 + math.sin(a) * R * .62
            for b in (a + .9, a - .9): line([(x, y), (x + math.cos(b) * 2.8, y + math.sin(b) * 2.8)], 1.5)

OFFS = [(0, 0)] + [(int(r * math.cos(a * math.pi / 6)), int(r * math.sin(a * math.pi / 6))) for r in (8, 16, 24) for a in range(12)]
_CACHE = {}
def sprite(kind):
    """آیکن سفید سه‌بعدی (RGBA، S×S) با سایه و لبهٔ تیره."""
    if kind in _CACHE: return _CACHE[kind]
    N = S * SS; pad = 3 * SS; inner = N - 2 * pad; u = inner / 24.0
    m = Image.new('L', (N, N), 0); _glyph(ImageDraw.Draw(m), kind, u)
    big = Image.new('L', (N, N), 0); big.paste(m, (pad, pad))
    m = big.crop((0, 0, N, N))
    # حاشیه‌ای که جا برای سایه/لبه دارد: ماسک را کمی کوچک کن تا بیرون نزند
    m = m.resize((N, N))
    k = int(1.3 * SS) | 1
    edge = m.filter(ImageFilter.MaxFilter(k))
    sh = Image.new('L', (N, N), 0); sh.paste(edge, (int(1.2 * SS), int(1.6 * SS))); sh = sh.filter(ImageFilter.GaussianBlur(1.4 * SS))
    out = Image.new('RGBA', (N, N), (0, 0, 0, 0))
    out.alpha_composite(Image.merge('RGBA', (Image.new('L', (N, N), 20), Image.new('L', (N, N), 20), Image.new('L', (N, N), 20), sh.point(lambda v: int(v * 0.75)))))
    out.alpha_composite(Image.merge('RGBA', (Image.new('L', (N, N), 45), Image.new('L', (N, N), 45), Image.new('L', (N, N), 50), edge.point(lambda v: int(v * 0.9)))))
    y = np.linspace(0, 1, N, dtype=np.float32)[:, None]; x = np.linspace(0, 1, N, dtype=np.float32)[None, :]
    g = np.clip(255 - 38 * (0.65 * y + 0.35 * x), 0, 255).astype(np.uint8)          # شیب روشنایی از بالا-چپ (سفید) به پایین-راست (خاکستری روشن)
    body = np.stack([g, g, g, np.array(m)], -1); out.alpha_composite(Image.fromarray(body, 'RGBA'))
    sp = out.resize((S, S), Image.LANCZOS); _CACHE[kind] = sp; return sp

def pick(Hd, ov_alpha, fx0, fy0, step=40, half=14):
    """[(x, y, kind)] در مختصات تصویر. Hd: دیکشنری ماسک‌های هشدار (field ها روی کادر داده)؛ ov_alpha: آلفای لایهٔ مرز/نام (H×W)."""
    wl = Hd.get('warn')
    if wl is None: return []
    lv = np.nan_to_num(wl).astype(np.int8); h, w = lv.shape
    blocked = ov_alpha > 25                              # ov_alpha: اگر RGBA کامل (H×W×4) داده شود فقط پیکسل‌های تیره (نام‌ها و مرز استان) مانع‌اند، نه خطوط نازک آبی شهرستان
    if ov_alpha.ndim == 3: blocked = (ov_alpha[..., 3] > 60) & (ov_alpha[..., :3].astype(np.int32).sum(-1) < 330)
    try:
        from scipy.ndimage import binary_dilation, uniform_filter
        blocked = binary_dilation(blocked, iterations=1)
        okfrac = uniform_filter((lv >= ICON_MIN).astype(np.float32), size=2 * half + 1, mode='constant')
    except Exception: okfrac = (lv >= ICON_MIN).astype(np.float32)
    keys = [k for k in PRI if k in Hd and Hd[k] is not None]
    MAXB = 0.30                                          # بیشینهٔ سهم پیکسل‌های نام/مرز زیر آیکن (آیکن زیر لایهٔ نام‌هاست؛ در ایران نام شهرستان‌ها پرتراکم است و آستانهٔ ~۱٪ هرگز برقرار نمی‌شد)
    def bfrac(x, y):
        X, Y = x - fx0, y - fy0
        if X < half or Y < half or X >= w - half or Y >= h - half: return 9.0
        if okfrac[Y, X] < 0.9: return 9.0
        return float(blocked[y - half:y + half + 1, x - half:x + half + 1].mean())
    out = []; used = []
    for gy in range(fy0 + half, fy0 + h - half, step):
        for gx in range(fx0 + half, fx0 + w - half, step):
            if lv[gy - fy0, gx - fx0] < ICON_MIN: continue
            spot = None; sb = MAXB
            for dx, dy in OFFS:                              # کم‌شلوغ‌ترین جا در همسایگی (نه اولین جای مجاز)
                x, y = gx + dx, gy + dy; b = bfrac(x, y)
                if b < sb and not any(abs(x - ux) < S * 0.9 and abs(y - uy) < S * 0.9 for ux, uy in used): spot = (x, y); sb = b
            if spot is None: continue
            x, y = spot; Y0, X0 = y - fy0, x - fx0; best = None; bl = 0
            for k in keys:                                    # بالاترین سطح در جعبه؛ در تساوی اولویت PRI
                a = Hd[k][max(0, Y0 - 3):Y0 + 4, max(0, X0 - 3):X0 + 4]; l = float(np.nanmax(a)) if a.size and not np.all(np.isnan(a)) else 0
                if l > bl: bl, best = l, k
            if best is None or bl < ICON_MIN: continue
            used.append((x, y)); out.append((x, y, KIND[best]))
    return out[:90]

def draw(im, icons):
    for x, y, kind in icons: im.alpha_composite(sprite(kind), (int(x - S // 2), int(y - S // 2)))

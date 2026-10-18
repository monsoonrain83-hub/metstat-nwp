# -*- coding: utf-8 -*-
"""wind_tile.py — کاشی باد برای «ذرات باد» نمایشگر. WebP بدون‌اتلاف ۱۸۰×۱۲۱ (شبکهٔ ۰٫۲۵° خاورمیانه، شمال بالا):
ردیف ۰ = سرایند (پیکسل ۰: R = گام×۱۰ [گره]، G = نسخه=۱)، ردیف‌های ۱..۱۲۰ = داده؛ R = u (به شرق)، G = v (به شمال)؛ مقدار = q·گام، q = بایت − ۱۲۸؛ ۰ = بدون داده.
واحد گره (kt)، جهت: مؤلفه‌های رو‌به‌شرق/رو‌به‌شمال (نه «از»)."""
import io
import numpy as np
from PIL import Image
STEP = 8              # از شبکهٔ ۳۲ پیکسل/درجه به ۴ پیکسل/درجه
VERSION = 1

def _q(a, scale):
    a = np.asarray(a, dtype=np.float64)[STEP // 2::STEP, STEP // 2::STEP]
    return np.where(np.isfinite(a), np.clip(np.round(a / scale) + 128, 1, 255), 0).astype(np.uint8)

def encode(u, v, scale):
    qu, qv = _q(u, scale), _q(v, scale); h, w = qu.shape
    a = np.zeros((h + 1, w, 3), np.uint8); a[0, 0] = (int(round(scale * 10)), VERSION, 0); a[1:, :, 0] = qu; a[1:, :, 1] = qv
    b = io.BytesIO(); Image.fromarray(a, 'RGB').save(b, 'WEBP', lossless=True, quality=100, method=4); return b.getvalue()

def decode(webp):
    a = np.asarray(Image.open(io.BytesIO(webp)).convert('RGB')).astype(np.int64); scale = a[0, 0, 0] / 10.0
    u = np.where(a[1:, :, 0] > 0, (a[1:, :, 0] - 128) * scale, np.nan); v = np.where(a[1:, :, 1] > 0, (a[1:, :, 1] - 128) * scale, np.nan)
    return scale, u, v

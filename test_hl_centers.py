import numpy as np, hl_centers as H
PX = H.PXD; W, Hh = 45 * PX, 30 * PX
yy, xx = np.mgrid[0:Hh, 0:W].astype(np.float32); lon = 20 + xx / PX; lat = 42 - yy / PX
def bump(lo, la, amp, s): return amp * np.exp(-(((lon - lo) ** 2 + (lat - la) ** 2) / (2 * s * s)))
ok = 0
def check(c, e):
    global ok; ok += 1
    if not c: raise SystemExit('FAIL ' + e)
# MSLP: پس‌زمینه ۱۰۱۵ ؛ کم‌فشار ۱۰۰۰ در (35E,30N)، پرفشار ۱۰۳۰ در (55E,36N)
f = 1015 - bump(35, 30, 15, 3) + bump(55, 36, 15, 3)
c = H.find_centers(f, 'msl')
Ls = [o for o in c if o[0] == 'L']; Hs = [o for o in c if o[0] == 'H']
check(len(Ls) == 1 and len(Hs) == 1, 'تعداد مراکز ' + str(c))
check(abs(20 + Ls[0][1] / PX - 35) < 0.3 and abs(42 - Ls[0][2] / PX - 30) < 0.3, 'مکان L')
check(abs(20 + Hs[0][1] / PX - 55) < 0.3 and abs(42 - Hs[0][2] / PX - 36) < 0.3, 'مکان H')
check(abs(Ls[0][3] - 1000) < 1.2 and abs(Hs[0][3] - 1030) < 1.2, 'مقدار مرکز')
# میدان تخت/ضعیف → هیچ مرکزی (آستانهٔ برجستگی)
check(H.find_centers(1015 + bump(40, 35, 0.8, 3), 'msl') == [], 'مرکز ضعیف نباید ثبت شود')
# شیب خطی بدون اکسترمم داخلی → هیچ
check(H.find_centers(1000 + 0.5 * (lon - 20), 'msl') == [], 'شیب خطی')
# لبهٔ کاشی: مرکز نزدیک مرز حذف
check(H.find_centers(1015 - bump(20.8, 30, 15, 2), 'msl') == [], 'حاشیه')
# ارتفاع ۸۵۰ با ماسک زیرِ زمین: ps کمتر از ۸۵۰+۱۵ → حذف؛ بالاتر → ثبت
g = 150 - bump(40, 33, 10, 3); ps_low = np.full_like(g, 800.0); ps_ok = np.full_like(g, 1000.0)
check(H.find_centers(g, 850, ps=ps_low) == [], 'زیر زمین')
check(len(H.find_centers(g, 850, ps=ps_ok)) == 1, 'روی زمین')
# دو کم‌فشار نزدیک (کمتر از RAD) → یکی می‌ماند
f2 = 1015 - bump(35, 30, 15, 1.2) - bump(37, 30, 12, 1.2)
check(len([o for o in H.find_centers(f2, 'msl') if o[0] == 'L']) == 1, 'حذف هم‌پوشانی')
# NaN
f3 = f.copy(); f3[100:140, 100:140] = np.nan; check(len(H.find_centers(f3, 'msl')) == 2, 'NaN')
# خروجی تصویر
b = H.encode_layer(c, W, Hh); check(b[:4] == b'RIFF' and len(b) < 60000, 'WebP ' + str(len(b)))
check(H.encode_layer([], W, Hh) is None, 'بدون مرکز → None')
from PIL import Image; import io
im = Image.open(io.BytesIO(b)).convert('RGBA'); a = np.array(im)
check((a[..., 3] > 0).sum() > 500 and (a[..., 3] == 0).mean() > 0.99, 'لایه شفاف است')
print('ALL OK', ok)

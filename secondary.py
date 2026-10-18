# -*- coding: utf-8 -*-
"""MetStat — نقشه‌های ثانویه: همرفت، شدت همرفت، تگرگ، آذرخش، سیل‌خیزی و مجموعهٔ هشدارهای جوی.

روش: برای هر گام، چند شاخص مستقل از میدان‌های مدل محاسبه و با آستانه‌های مرجع به بازهٔ ۰..۱ نرمال می‌شوند؛ ترکیب وزنی
(وزن‌ها بر پایهٔ نتایج راستی‌آزمایی منتشرشده؛ شاخص‌هایی که در داده نیستند از میانگین کنار می‌روند و وزن‌ها بازنرمال می‌شوند)
سپس به طبقه‌های گسسته تبدیل می‌شود. در پایان بیشینهٔ هر خطر در پنجرهٔ ۶ ساعته، ۲۴ ساعته و تجمعی نگه‌داشته می‌شود.
مراجع (آستانه‌ها و وزن‌ها):
 - Haklander & Van Delden (2003, Atmos. Res. 67–68): LI بهترین پیش‌بین رعدوبرق؛ KO و Showalter و TT متوسط؛ K و SWEAT ضعیف
   (آستانه‌های «رعدوبرق ممکن»: LI≤3، KO≤1.9، SHOW≤4.2، TT≥46.7، CAPE≥170). وزن‌ها بر همین ترتیب و با سهم کم‌تر برای K/SWEAT.
 - Craven & Brooks (2004): CAPE×shear 0–6km ≥ 20000 m³/s³؛ SPC: SHIP (Johnson & Sugden 2014) و LHP؛ ناحیهٔ رشد تگرگ −10..−30°C.
 - Romps et al. (2014): آهنگ آذرخش ∝ CAPE×شدت بارش.
 - FFPI (NOAA/NWS) برای سیل‌خیزی: بارش مؤثر × آمادگی زمین (شیب، رطوبت خاک).
 - Environment Canada (باد سرد)، Steadman (دمای محسوس)، NWS (شاخص گرما) برای هشدارهای دمایی.
آستانه‌ها برای «آب‌وهوای خشک ایران» قابل تنظیم‌اند؛ هنوز با مشاهدات ایران واسنجی نشده‌اند (فقط راستی‌آزمایی عمومی).
"""
import numpy as np
from datetime import timedelta

EPS = 1e-6
WINS = [('6', 'بیشینهٔ ۶ ساعته', '6-hour max'), ('24', 'بیشینهٔ ۲۴ ساعته (تا ۲۱ UTC)', '24-hour max (to 21Z)'), ('acc', 'بیشینهٔ تجمعی از ابتدای اجرا', 'cumulative max since run start')]
LV5 = dict(en=['None', 'Weak', 'Moderate', 'Strong', 'Very strong', 'Extreme'], fa=['بدون', 'ضعیف', 'متوسط', 'قوی', 'بسیار قوی', 'شدید'])
W4 = dict(colors=['#ffffff', '#ffeb3b', '#ff9800', '#e53935'], names=['None', 'Yellow', 'Orange', 'Red'], fa=['بدون', 'زرد', 'نارنجی', 'قرمز'])
SECSC = {
    'cvp':   dict(colors=['#ffffff', '#b7e4a3', '#fff176', '#ffb74d', '#e53935', '#8e24aa'], names=LV5['en'], fa=LV5['fa']),
    'cvi':   dict(colors=['#ffffff', '#b7e4a3', '#fff176', '#ffb74d', '#e53935', '#8e24aa'], names=['None', 'Weak', 'Moderate', 'Strong', 'Severe', 'Extreme'], fa=['بدون', 'ضعیف', 'متوسط', 'قوی', 'شدید', 'بسیار شدید']),
    'hail':  dict(colors=['#ffffff', '#c6e2ff', '#64b5f6', '#1e5fd0', '#7b1fa2', '#d500f9'], names=['None', 'Low', 'Moderate', 'High', 'Very high', 'Extreme'], fa=['بدون', 'کم', 'متوسط', 'زیاد', 'بسیار زیاد', 'شدید']),
    'ltg':   dict(colors=['#ffffff', '#fff9c4', '#ffee58', '#ffb300', '#fb8c00', '#d50000'], names=LV5['en'], fa=LV5['fa']),
    'flood': dict(colors=['#ffffff', '#bbdefb', '#64b5f6', '#1976d2', '#6a1b9a'], names=['None', 'Minor', 'Moderate', 'Major', 'Extreme'], fa=['بدون', 'کم', 'متوسط', 'زیاد', 'بسیار زیاد']),
    'warn':  W4,
}
for _k, _v in SECSC.items(): _v['edges'] = [i - 0.5 for i in range(len(_v['colors']) + 1)]

# شناسه → (عنوان فارسی، عنوان انگلیسی، کلید مقیاس، مدل‌ها: 'ecg' یا 'all')
PRODUCTS = {
    'cvp':    ('پتانسیل همرفت (ترکیب شاخص‌ها)', 'Convective potential (index composite)', 'cvp', 'ecg'),
    'cvi':    ('شدت همرفت و توفان تندری', 'Convective/thunderstorm intensity', 'cvi', 'ecg'),
    'hail':   ('پتانسیل تگرگ', 'Hail potential', 'hail', 'ecg'),
    'ltg':    ('پتانسیل آذرخش', 'Lightning potential', 'ltg', 'ecg'),
    'flood':  ('سیل‌خیزی (بارش × شیب × رطوبت خاک)', 'Flash-flood potential', 'flood', 'all'),
    'wrainl': ('هشدار بارش (باران، همهٔ شدت‌ها)', 'Warning: rainfall (all intensities)', 'warn', 'all'),
    'wrain':  ('هشدار بارش سنگین', 'Warning: heavy rain', 'warn', 'all'),
    'wsnow':  ('هشدار بارش برف', 'Warning: snowfall', 'warn', 'all'),
    'wice':   ('هشدار باران یخ‌زده / یخ‌بندان بارشی', 'Warning: freezing rain / icing', 'warn', 'all'),
    'wwind':  ('هشدار باد و تندباد', 'Warning: wind gusts', 'warn', 'all'),
    'wdust':  ('هشدار خیزش گردوغبار (پتانسیل)', 'Warning: blowing dust (potential)', 'warn', 'all'),
    'wfog':   ('هشدار مه / دید افقی', 'Warning: fog / visibility', 'warn', 'all'),
    'wfrost': ('هشدار یخبندان (هوا)', 'Warning: air frost', 'warn', 'all'),
    'wgfrost': ('هشدار یخبندان سطح زمین', 'Warning: ground frost', 'warn', 'all'),
    'wcold':  ('هشدار سوزباد (Wind chill)', 'Warning: wind chill', 'warn', 'all'),
    'wheat':  ('هشدار گرما', 'Warning: heat', 'warn', 'all'),
    'whum':   ('هشدار شرجی (گرمای مرطوب)', 'Warning: humid heat', 'warn', 'all'),
    'wtstm':  ('هشدار توفان تندری', 'Warning: thunderstorm', 'warn', 'ecg'),
    'whail':  ('هشدار تگرگ', 'Warning: hail', 'warn', 'ecg'),
    'wltg':   ('هشدار آذرخش', 'Warning: lightning', 'warn', 'ecg'),
    'wflood': ('هشدار سیل', 'Warning: flash flood', 'warn', 'all'),
    'wlog':   ('هشدار آبگرفتگی (شهری/دشت)', 'Warning: waterlogging', 'warn', 'all'),
    'warn':   ('هشدار جوی ترکیبی (بیشینهٔ همهٔ خطرها)', 'Combined atmospheric warning', 'warn', 'all'),
}
HAZ = list(PRODUCTS)

# ---------------------------------------------------------------- ابزارها
def nz(x, lo, hi):
    """نرمال‌سازی خطی به ۰..۱ (lo → ۰، hi → ۱؛ می‌تواند نزولی باشد)؛ NaN حفظ می‌شود."""
    x = np.asarray(x, np.float32); return np.clip((x - lo) / (hi - lo), 0, 1)
def cls(x, th):
    x = np.asarray(x, np.float32); return np.where(np.isnan(x), np.nan, np.digitize(np.nan_to_num(x), th)).astype(np.float32)
def wavg(items):
    """میانگین وزنی روی شاخص‌های موجود؛ NaN فقط جایی که هیچ شاخصی نیست."""
    num = 0; den = 0
    for w, a in items:
        if a is None: continue
        m = ~np.isnan(a); num = num + w * np.where(m, a, 0); den = den + w * m
    return None if isinstance(den, int) else np.where(den > 0, num / np.maximum(den, EPS), np.nan).astype(np.float32)
def es(tc): return 6.112 * np.exp(17.67 * tc / (tc + 243.5))
def td_from_rh(tc, rh):
    rh = np.clip(rh, 1, 100); g = np.log(rh / 100) + 17.67 * tc / (tc + 243.5); return 243.5 * g / (17.67 - g)
def mixr_gkg(tc, rh, p):
    e = es(tc) * np.clip(rh, 0, 100) / 100.0; return 1000.0 * 0.622 * e / np.maximum(p - e, 1.0)
def theta_e(tc, td, p):
    """θe بولتون (K)."""
    T = tc + 273.15; Td = td + 273.15
    Tl = 1 / (1 / np.maximum(Td - 56, 1) + np.log(T / Td) / 800) + 56
    r = mixr_gkg(tc, 100 * es(td) / es(tc), p) if False else 1000.0 * 0.622 * es(td) / np.maximum(p - es(td), 1.0)
    return T * (1000.0 / p) ** (0.2854 * (1 - 0.00028 * r)) * np.exp((3.376 / Tl - 0.00254) * r * (1 + 0.00081 * r))
def parcel_to_500(t, td, p0, t500):
    """ذرهٔ بالابرده از p0 (هکتوپاسکال) تا ۵۰۰: صعود خشک تا LCL و سپس شبه‌بی‌دررو؛ خروجی: t500 − Tparcel (LI/Showalter)."""
    T = t + 273.15; Td = td + 273.15
    Tl = 1 / (1 / np.maximum(Td - 56, 1) + np.log(T / Td) / 800) + 56
    pl = p0 * (Tl / T) ** 3.5
    tt = Tl.copy(); p = pl.copy(); steps = 24; dp = (p - 500.0) / steps
    for _ in range(steps):
        tc = tt - 273.15; e = es(tc); r = 0.622 * e / np.maximum(p - e, 1); Lv = 2.501e6
        g = (287.04 * tt + Lv * r) / (1005.7 + Lv * Lv * r * 0.622 / (287.04 * tt * tt)) / p
        tt = tt - g * dp; p = p - dp
    return np.where(p0 > 520, (t500 + 273.15) - tt, np.nan)
def hyps_heights(T, zs, ps):
    """ارتفاع ترازهای فشاری (m، از سطح دریا) با رابطهٔ هیپسومتریک از سطح زمین (zs، ps) بالا؛ T: دیکشنری p → °C."""
    z = {}; zprev, pprev, Tprev = zs, ps, None
    for p in (925, 850, 700, 500, 300):
        if T.get(p) is None: return None
        Tm = T[p] + 273.15 if Tprev is None else 0.5 * (T[p] + Tprev) + 273.15
        zl = np.where(pprev > p, zprev + 29.27 * Tm * np.log(np.maximum(pprev, p) / p), np.nan)
        z[p] = np.where(np.isnan(zl), np.nan, zl); zprev = np.where(np.isnan(zl), zprev, zl); pprev = np.where(np.isnan(zl), pprev, p); Tprev = T[p]
    return z
def iso_height(T, z, zs, t0, t2=None):
    """ارتفاع هم‌دمای t0 با درون‌یابی خطی بین ترازها (از پایین به بالا)؛ اگر دمای سطح ≤ t0 باشد، ارتفاع سطح."""
    lv = [p for p in (925, 850, 700, 500, 300) if T.get(p) is not None and z.get(p) is not None]
    out = np.full(np.shape(zs), np.nan, np.float32); done = np.zeros(np.shape(zs), bool)
    if t2 is not None:
        m = t2 <= t0; out = np.where(m, zs, out); done |= m
    for a, b in zip(lv[:-1], lv[1:]):
        Ta, Tb, za, zb = T[a], T[b], z[a], z[b]
        m = (~done) & (Ta >= t0) & (Tb < t0)
        zz = za + (Ta - t0) / np.maximum(Ta - Tb, EPS) * (zb - za)
        out = np.where(m, zz, out); done |= m
    top = lv[-1]; m = (~done) & (T[top] >= t0); out = np.where(m, z[top], out)
    return out

# ---------------------------------------------------------------- شاخص‌های ترمودینامیکی/برشی
def indices(F):
    """میدان‌های ورودی → شاخص‌ها (همه روی شبکهٔ نمایش). کلیدهای ناموجود None می‌مانند."""
    g = F.get; I = {}
    T = {p: g(f't{p}') for p in (925, 850, 700, 500, 300)}; RH = {p: g(f'rh{p}') for p in (925, 850, 700, 500, 300)}
    Td = {p: (td_from_rh(T[p], RH[p]) if T[p] is not None and RH[p] is not None else None) for p in T}
    have = lambda *ps: all(T[p] is not None and RH[p] is not None for p in ps)
    I['cape'], I['cin'] = g('cape'), g('cin')
    if have(850, 700, 500):
        I['tt'] = T[850] + Td[850] - 2 * T[500]
        I['k'] = (T[850] - T[500]) + Td[850] - (T[700] - Td[700])
        I['show'] = parcel_to_500(T[850], Td[850], 850.0, T[500])
        I['spr700'] = T[700] - Td[700]
        dz = 29.27 * (0.5 * (T[700] + T[500]) + 273.15) * np.log(700.0 / 500.0) / 1000.0
        I['lr75'] = (T[700] - T[500]) / np.maximum(dz, 1.0)
        dz85 = 29.27 * (0.5 * (T[850] + T[500]) + 273.15) * np.log(850.0 / 500.0) / 1000.0
        I['lr85'] = (T[850] - T[500]) / np.maximum(dz85, 1.0)
        I['rhmid'] = (RH[850] + RH[700] + RH[500]) / 3.0
        if g('t2') is not None and g('rh2') is not None and g('ps') is not None:
            td2 = td_from_rh(g('t2'), g('rh2'))
            I['ko'] = 0.5 * (theta_e(T[500], Td[500], 500.0) + theta_e(T[700], Td[700], 700.0)) - 0.5 * (theta_e(g('t2'), td2, g('ps')) + theta_e(T[850], Td[850], 850.0))   # KO با تراز سطحی به‌جای ۱۰۰۰ هکتوپاسکال (فلات ایران)
            I['li'] = g('li') if g('li') is not None else parcel_to_500(g('t2'), td2, g('ps'), T[500])
            I['mr'] = mixr_gkg(T[850], RH[850], 850.0)
    if I.get('li') is None and g('li') is not None: I['li'] = g('li')
    if g('u850') is not None and g('u500') is not None and g('v850') is not None and g('v500') is not None and 'tt' in I:
        f850 = np.hypot(g('u850'), g('v850')) * 1.94384; f500 = np.hypot(g('u500'), g('v500')) * 1.94384
        d = lambda u, v: (np.degrees(np.arctan2(-u, -v)) + 360) % 360
        sh = np.sin(np.radians(d(g('u500'), g('v500')) - d(g('u850'), g('v850'))))
        I['sweat'] = 12 * np.maximum(Td[850], 0) + 20 * np.maximum(I['tt'] - 49, 0) + 2 * f850 + f500 + 125 * (np.maximum(sh, 0) + 0.2)
    if all(g(k) is not None for k in ('u10', 'v10', 'u500', 'v500')): I['s06'] = np.hypot(g('u500') - g('u10'), g('v500') - g('v10'))
    if all(g(k) is not None for k in ('u850', 'v850', 'u500', 'v500')): I['s85'] = np.hypot(g('u500') - g('u850'), g('v500') - g('v850'))
    I['gdi'], I['ki_x'], I['si'] = g('gdi'), g('ki'), g('si')
    I['pw'] = g('pw')
    # ناحیهٔ رشد تگرگ و تراز صفر درجه
    zs = g('zs'); ps = g('ps')
    if zs is not None and ps is not None and all(T[p] is not None for p in (925, 850, 700, 500, 300)):
        z = {p: g(f'z{p}') for p in T}
        if any(v is None for v in z.values()): z = hyps_heights(T, zs, ps)
        if z is not None:
            t2 = g('t2'); z0 = iso_height(T, z, zs, 0.0, t2); z10 = iso_height(T, z, zs, -10.0, t2); z30 = iso_height(T, z, zs, -30.0, t2)
            I['fzl'] = z0 - zs; I['hgz'] = np.where(np.isnan(z10) | np.isnan(z30), np.nan, z30 - z10)
    return I

# ---------------------------------------------------------------- CAPE/CIN روی دریا در نیمهٔ گرم سال
# CAPE (SB/ML) و CIN مدل‌ها از ۱ اردیبهشت تا ۵ آبان (۲۱ آوریل تا ۲۷ اکتبر) روی خلیج فارس/دریای عمان، دریای سرخ و مدیترانه
# برای پتانسیل همرفت خشکی قابل‌اعتماد نیست؛ وزن این دو شاخص آنجا ≈۵٪ می‌شود. خشکی و بقیهٔ شاخص‌ها بدون تغییر.
SEA_BOXES = [(47.5, 63.0, 22.0, 30.6), (32.2, 43.8, 12.5, 29.5), (-6.0, 36.2, 30.0, 41.0), (-6.0, 19.0, 41.0, 46.0)]   # lon0, lon1, lat0, lat1
import os
CV_MODE = os.environ.get('CV_MODE', 'old').strip().lower()      # old = فرمول وزنی قبلی (راستی‌آزمایی‌شده)؛ new = روش گروهی-ضربی صفحهٔ تحلیل + قید دریا
SEA_F = 0.0                                      # وزن CAPE/CIN (و محصولات وابسته) روی دریا = صفر؛ خشکی دست‌نخورده
W_CAPE_LAND = 0.20; W_CAPE_SEA = W_CAPE_LAND * SEA_F          # سهم نهایی CAPE در ترکیب ≈ ۵٪ (چون مجموع وزن بقیه ≈ ۰٫۸)
CIN_PEN_LAND = 0.5; CIN_PEN_SEA = CIN_PEN_LAND * SEA_F
if CV_MODE != 'new': SEA_F = 1.0; W_CAPE_SEA = 0.04; CIN_PEN_SEA = 0.05        # حالت قدیم: وزن‌های دریا مثل نسخهٔ پیش از §78
def in_cape_window(vt):
    md = (vt.month, vt.day); return (4, 21) <= md <= (10, 27)
def sea_mask(lon, lat, hsurf, dem=None):
    """دریا = داخل جعبه‌های سه دریا و ارتفاع سطح مدل ≤ ۵ متر؛ اگر ارتفاع مدل نبود، از DEM (مقدار ≤ ۰) استفاده می‌شود.
    اگر هیچ‌کدام نبود None برمی‌گرداند (و فراخوان باید هشدار بدهد)."""
    box = np.zeros(np.shape(lat), bool)
    for lo0, lo1, la0, la1 in SEA_BOXES: box |= (lon >= lo0) & (lon <= lo1) & (lat >= la0) & (lat <= la1)
    if hsurf is not None: m = box & (np.nan_to_num(hsurf, nan=999.0) <= 0.5)      # فقط یاخته‌های واقعاً دریا؛ خشکی کم‌ارتفاع ساحلی (خوزستان، بصره، دلتای نیل …) دریا حساب نمی‌شود
    elif dem is not None: m = box & (np.nan_to_num(dem, nan=999.0) <= 0.0)
    else: return None
    if dem is not None: m &= ~(np.nan_to_num(dem, nan=-999.0) > 1.0)              # DEM دقیق‌تر: هر جا خشکی است دریا نیست
    return m

# ---------------------------------------------------------------- پتانسیل همرفت: همان روش صفحهٔ «تحلیل و هشدار» آفلاین (21_convection_indices.js)
# گروه‌ها: inst (ناپایداری)، trig (CIN)، moist (رطوبت)، sig (بارش همرفتی مدل). احتمال = Fi × میانگین هندسی (trig، moist، sig)
# یعنی «همهٔ جوانب لازم‌اند»: ناپایداری بالا بدون رطوبت/ماشه/بارش مدل، پتانسیل بالا نمی‌دهد (برخلاف جمع وزنی که یک عامل قوی کل را بالا می‌برد).
# رمپ سه‌نقطه‌ای (۰ → ۰٫۵ → ۱) و وزن علمی فصلی (فصل گرم ۲۰ فروردین تا ۱۵ آبان) عیناً از سایت.
CV_RAMP = dict(cape=(100, 800, 1500), cin=(200, 75, 25), li=(2, -1, -4), si=(3, 0, -3), ki=(20, 28, 35), tt=(44, 48, 52), gdi=(5, 25, 45), lapse=(5.5, 6.5, 7.5),
               sweat=(150, 250, 300), t500=(-8, -14, -20), pwat=(10, 18, 30), rh=(40, 60, 80), td2m=(0, 8, 16), cprec=(0.1, 1, 5))
CV_GRP = dict(cape='inst', li='inst', si='inst', ki='inst', tt='inst', gdi='inst', lapse='inst', sweat='inst', t500='inst', cin='trig', pwat='moist', rh='moist', td2m='moist', cprec='sig')
CV_W = {True: dict(li=1.5, si=1.5, ki=1.3, cape=1.3, gdi=1.2, tt=1.0, lapse=1.0, sweat=0.8, t500=0.8, cin=1.0, pwat=1.0, td2m=1.0, rh=0.8, cprec=1.2),
        False: dict(li=1.2, si=1.3, ki=1.2, cape=0.6, gdi=0.8, tt=1.3, lapse=1.2, sweat=0.8, t500=1.4, cin=0.8, pwat=1.0, td2m=0.9, rh=1.1, cprec=1.2)}
def warm_season(vt):
    """فصل گرم سایت: ۲۰ فروردین (≈۹ آوریل) تا ۱۵ آبان (≈۶ نوامبر)."""
    return vt is None or (4, 9) <= (vt.month, vt.day) <= (11, 6)
def cv_ramp(v, r):
    v = np.asarray(v, np.float32); a, b, c = r
    t1 = (v - a) / (b - a); t2 = (v - b) / (c - b)
    return np.where(np.isnan(v), np.nan, np.where((b - a) * (v - b) <= 0, np.clip(0.5 * t1, 0, 0.5), np.clip(0.5 + 0.5 * t2, 0.5, 1))).astype(np.float32)
def cv_potential(V, warm, SW=None):
    """V: دیکشنری شاخص‌ها (None = ناموجود)؛ SW: ماسک دریا در بازهٔ زمانی ضعف CAPE/CIN. خروجی 0..1 (NaN جایی که هیچ شاخصی نیست)."""
    W = CV_W[bool(warm)]; shp = None
    for v in V.values():
        if v is not None: shp = np.shape(v); break
    if shp is None: return None
    G = {g: np.zeros(shp, np.float32) for g in ('inst', 'trig', 'moist', 'sig')}; GW = {g: np.zeros(shp, np.float32) for g in G}
    GWl = {g: np.zeros(shp, np.float32) for g in G}; DEF = {g: np.zeros(shp, np.float32) for g in G}
    for k, v in V.items():
        if v is None or k not in CV_RAMP: continue
        a = cv_ramp(v, CV_RAMP[k]); g = CV_GRP[k]; ok = ~np.isnan(a); w = np.float32(W[k]) * ok
        if SW is not None and k in ('cape', 'cin'):
            wl = np.where(SW, w * SEA_F, w).astype(np.float32); DEF[g] += w - wl; w = wl      # روی دریا وزن کم؛ سهم حذف‌شده برای گروه‌های تک‌شاخصی خنثی (۰٫۵) می‌شود
        else: wl = w
        G[g] += w * np.nan_to_num(a); GW[g] += w; GWl[g] += wl
    for g in G:
        m = (DEF[g] > 0) & ~(GWl[g] > 0); G[g] = G[g] + np.where(m, 0.5 * DEF[g], 0); GW[g] = GW[g] + np.where(m, DEF[g], 0)
    lg = np.zeros(shp, np.float32); wt = np.zeros(shp, np.float32)
    for g in ('trig', 'moist', 'sig'):
        ok = GW[g] > 0; fg = np.maximum(0.05, G[g] / np.maximum(GW[g], EPS)); lg += np.where(ok, GW[g] * np.log(fg), 0); wt += np.where(ok, GW[g], 0)
    M = np.where(wt > 0, np.exp(lg / np.maximum(wt, EPS)), 1.0)
    Fi = np.where(GW['inst'] > 0, G['inst'] / np.maximum(GW['inst'], EPS), np.nan)
    p = np.where(np.isnan(Fi), M, Fi * M)
    return np.where((GW['inst'] + wt) > 0, p, np.nan).astype(np.float32)

# ---------------------------------------------------------------- واداشت دینامیکی (ترازهای فوقانی × فشار سطحی)
# مبانی: Sutcliffe (۱۹۴۷): واگرایی بالای تراز ۵۰۰ hPa (زیر ترپوپوز) ↔ همگرایی سطحی/صعود؛ همگرایی بالا ↔ فرونشینی و واگرایی سطحی.
# Doswell (۱۹۸۷) و Johns & Doswell (۱۹۹۲): همرفت عمیق = ناپایداری + رطوبت + بالابری؛ بالابری ترازهای بالا (واگرایی ۳۰۰، رودبار، PVA ۵۰۰) ماشه و CIN را تنظیم می‌کند.
# چهار حالت: کم‌فشار سطحی + واگرایی بالا = تشدید؛ کم‌فشار + همگرایی بالا = سرکوب جریان صعودی؛
# پرفشار + واگرایی بالا = تضعیف سرکوب و افزایش اندکِ احتمال؛ پرفشار + همگرایی بالا = سرکوب شدید و پایداری. مقادیر رأس‌ها قراردادی و قابل تنظیم‌اند و بین آن‌ها درون‌یابی دوخطی می‌شود.
DYN_ON = os.environ.get('CV_DYN', '1').strip() != '0'
DYN_CORNER = dict(low_div=1.0, low_conv=-0.6, high_div=0.3, high_conv=-1.0)
DYN_UP, DYN_SP, DYN_PVA, DYN_SC, DYN_JET = 1.5e-5, 4.0, 1.0e-8, 2.0e-5, 30.0        # مقیاس‌ها: واگرایی ۳۰۰ (1/s)، ناهنجاری فشار (hPa)، PVA ۵۰۰ (1/s²)، همگرایی ۱۰ متر (1/s)، آستانهٔ رودبار (m/s)
DYN_PVA_W, DYN_JET_W, DYN_POS_K, DYN_NEG_K = 0.25, 0.15, 0.30, 0.45                  # وزن PVA و رودبار؛ دامنهٔ اثر (افزایش تا ×۱٫۳۰، کاهش تا ×۰٫۵۵)
def _smooth(a, sig):
    if a is None: return None
    try:
        from scipy.ndimage import gaussian_filter
        return gaussian_filter(np.nan_to_num(a), sig, mode='nearest').astype(np.float32)
    except Exception: return np.nan_to_num(a).astype(np.float32)
def dyn_forcing(F):
    """خروجی: آرایهٔ −۱..+۱ (مثبت = تقویت همرفت، منفی = تضعیف) یا None اگر داده کافی نیست."""
    g = F.get
    if not DYN_ON or g('dxm') is None or g('dym') is None: return None
    dxm, dym = g('dxm'), g('dym'); dxkm = float(g('dxkm') or 25.0)
    sg = max(0.7, 120.0 / max(dxkm, 1.0))                         # هموارسازی ≈ ۱۲۰ km فقط روی ورودیِ دینامیکی (مقیاس همدیدی)
    def ddx(a): return np.gradient(a, axis=1) / dxm
    def ddy(a): return np.gradient(a, axis=0) / (-dym)             # ردیف‌ها از شمال به جنوب
    parts = {}
    if g('u300') is not None and g('v300') is not None:
        u3, v3 = _smooth(g('u300'), sg), _smooth(g('v300'), sg)
        parts['up'] = np.clip((ddx(u3) + ddy(v3)) / DYN_UP, -1, 1)
        parts['jet'] = np.clip((np.hypot(u3, v3) - DYN_JET) / 30.0, 0, 1)
    elif g('u500') is not None and g('v500') is not None:
        u5, v5 = _smooth(g('u500'), sg), _smooth(g('v500'), sg); parts['up'] = np.clip(0.7 * (ddx(u5) + ddy(v5)) / DYN_UP, -1, 1)
    if g('u500') is not None and g('v500') is not None and g('lat') is not None:
        u5, v5 = _smooth(g('u500'), sg), _smooth(g('v500'), sg); zeta = ddx(v5) - ddy(u5)
        beta = 2 * 7.292e-5 * np.cos(np.radians(g('lat'))) / 6.371e6
        adv = -(u5 * ddx(zeta) + v5 * ddy(zeta)) - v5 * beta         # فرارفت گردش مطلق: PVA > 0 ⇒ صعود
        parts['pva'] = np.clip(_smooth(adv, 1.0) / DYN_PVA, -1, 1)
    sfc = None
    if g('msl') is not None:
        m = _smooth(g('msl'), sg); big = _smooth(g('msl'), max(3.0, 600.0 / max(dxkm, 1.0)))
        sfc = np.clip(-(m - big) / DYN_SP, -1, 1)                    # +۱ = کم‌فشار نسبت به محیط بزرگ‌مقیاس، −۱ = پرفشار
    if g('u10') is not None and g('v10') is not None:
        u1, v1 = _smooth(g('u10'), sg), _smooth(g('v10'), sg); cv = np.clip(-(ddx(u1) + ddy(v1)) / DYN_SC, -1, 1)
        sfc = cv if sfc is None else np.clip(0.75 * sfc + 0.25 * cv, -1, 1)
    up = parts.get('up'); C = DYN_CORNER
    if up is None and sfc is None and 'pva' not in parts: return None
    if up is not None and sfc is not None:
        wu, wd, wl, wh = (1 + up) / 2, (1 - up) / 2, (1 + sfc) / 2, (1 - sfc) / 2
        dyn = wu * wl * C['low_div'] + wd * wl * C['low_conv'] + wu * wh * C['high_div'] + wd * wh * C['high_conv']
    elif up is not None: dyn = up * 0.8
    elif sfc is not None: dyn = sfc * 0.4
    else: dyn = np.zeros_like(parts['pva'])
    if 'pva' in parts: dyn = dyn + DYN_PVA_W * parts['pva']
    if 'jet' in parts and up is not None: dyn = dyn + DYN_JET_W * parts['jet'] * np.maximum(up, 0)      # رودبار قوی در ناحیهٔ واگرا بالابری را بیشتر می‌کند
    return np.clip(dyn, -1, 1).astype(np.float32)
def dyn_factor(d):
    return None if d is None else np.where(d >= 0, 1 + DYN_POS_K * d, 1 + DYN_NEG_K * d).astype(np.float32)

def sea_evidence(F, pr):
    """شاهد واقعی بودن همرفت روی دریا (True = مجاز به رده بالاتر از ۲): (۱) بارش مدل ≥ ۰٫۲ mm/h در همسایگی ≈۵۰ km و در ۳ ساعت گذشته؛
    یا (۲) واداشت دینامیکی قوی: هستهٔ سرد ۵۰۰ ≤ −۱۵°C، یا رودباد ≥ ۳۵ m/s (۳۰۰ یا ۵۰۰) همراه با ۵۰۰ ≤ −۱۲°C. بدون هیچ‌کدام از میدان‌ها → None (سقف اعمال نمی‌شود)."""
    ev = None
    r = None if pr is None else np.nan_to_num(pr)
    if F.get('p3') is not None: r = np.nan_to_num(F['p3']) / 3.0 if r is None else np.maximum(r, np.nan_to_num(F['p3']) / 3.0)
    if r is not None:
        dx = F.get('dxkm')
        if dx and dx > 0:
            try:
                from scipy.ndimage import maximum_filter
                k = int(max(1, round(100.0 / dx))) | 1
                if k > 1: r = maximum_filter(r, size=k, mode='nearest')
            except Exception: pass
        ev = r >= 0.2
    t5 = F.get('t500')
    if t5 is not None:
        jet = None
        for p in (300, 500):
            if F.get(f'u{p}') is not None and F.get(f'v{p}') is not None: j = np.hypot(F[f'u{p}'], F[f'v{p}']); jet = j if jet is None else np.fmax(jet, j)
        dyn = np.nan_to_num(t5, nan=0) <= -15
        if jet is not None: dyn = dyn | ((np.nan_to_num(jet) >= 35) & (np.nan_to_num(t5, nan=0) <= -12))
        ev = dyn if ev is None else (ev | dyn)
    return ev

# ---------------------------------------------------------------- طبقه‌بندی خطرها
def hazards(F):
    I = indices(F); g = F.get; out = {}
    pr = g('pr')
    SW = F.get('sea') if (F.get('sea') is not None and F.get('vt') is not None and in_cape_window(F['vt'])) else None      # دریا × بازهٔ زمانی
    _sw = lambda land: land if SW is None else np.where(SW, land * SEA_F, land).astype(np.float32)   # وزن روی دریا = SEA_F × خشکی
    wC = W_CAPE_LAND if SW is None else np.where(SW, W_CAPE_SEA, W_CAPE_LAND).astype(np.float32)
    cinP = CIN_PEN_LAND if SW is None else np.where(SW, CIN_PEN_SEA, CIN_PEN_LAND).astype(np.float32)
    if CV_MODE != 'new':
        comp = [(0.22, None if I.get('li') is None else nz(I['li'], 3.0, -6.0)),           # LI: بهترین در راستی‌آزمایی
                (wC, None if I['cape'] is None else nz(np.maximum(I['cape'], 0), 170, 3000)),
                (0.10, None if I.get('ko') is None else nz(I['ko'], 2.0, -4.0)),
                (0.10, None if I.get('tt') is None else nz(I['tt'], 46.7, 56.0)),
                (0.08, None if I.get('show') is None else nz(I['show'], 4.2, -6.0)),
                (0.06, None if I.get('k') is None else nz(I['k'], 21.0, 40.0)),
                (0.04, None if I.get('sweat') is None else nz(I['sweat'], 134, 400)),
                (0.05, None if I.get('gdi') is None else nz(I['gdi'], 25, 45)),
                (0.08, None if I.get('lr75') is None else nz(I['lr75'], 6.0, 8.5)),
                (0.06, None if (g('t2') is None or g('rh2') is None) else nz(td_from_rh(g('t2'), g('rh2')), 0.0, 16.0)),      # رطوبت سطحی (نقطهٔ شبنم ۲ متر)
                (0.07, None if I.get('rhmid') is None and I.get('pw') is None else wavg([(0.5, None if I.get('rhmid') is None else nz(I['rhmid'], 30, 75)), (0.5, None if I.get('pw') is None else nz(I['pw'], 8, 30))]))]
        sc = wavg(comp); cvp = None
        if sc is not None:
            if I['cin'] is not None: sc = sc * (1 - cinP * nz(-I['cin'], 50, 300))                # بازدارندگی همرفت
            if pr is not None: sc = sc + 0.10 * nz(pr, 0, 2)                                       # شاهد ماشه‌کشی: بارش همرفتی مدل
            if I.get('rhmid') is not None: sc = np.where(I['rhmid'] < 20, sc * 0.6, sc)
            dm = dyn_factor(dyn_forcing(F))
            if dm is not None: sc = sc * dm
            cvp = cls(np.clip(sc, 0, 1), [0.15, 0.30, 0.45, 0.60, 0.75]); out['cvp'] = cvp
    else:
        # ---- پتانسیل همرفت: روش گروهی-ضربی سایت (cv_potential) + شواهد ماشه‌کشی
        td2 = td_from_rh(g('t2'), g('rh2')) if (g('t2') is not None and g('rh2') is not None) else None
        V = dict(cape=None if I['cape'] is None else np.maximum(I['cape'], 0), cin=None if I['cin'] is None else np.abs(I['cin']), li=I.get('li'), si=I.get('show'), ki=I.get('k'), tt=I.get('tt'),
                 gdi=I.get('gdi'), lapse=I.get('lr75'), sweat=I.get('sweat'), t500=g('t500'), pwat=I.get('pw'), rh=g('rh700'), td2m=td2, cprec=pr)
        sc = cv_potential(V, warm_season(g('vt')), SW) if any(V[k] is not None for k in CV_GRP if CV_GRP[k] == 'inst') else None      # بدون هیچ شاخص ناپایداری، پتانسیل ساخته نمی‌شود
        cvp = None
        if sc is not None:
            if I.get('rhmid') is not None: sc = np.where(I['rhmid'] < 20, sc * 0.6, sc)            # ستون خشک
            dm = dyn_factor(dyn_forcing(F))
            if dm is not None: sc = sc * dm
            cvp = cls(np.clip(sc, 0, 1), [0.10, 0.20, 0.32, 0.45, 0.60])
            SEA = g('sea') if hasattr(g('sea'), 'shape') else None                                  # دریا در همهٔ فصل‌ها (نه فقط بازهٔ CAPE)
            if SEA is not None:
                ev = sea_evidence(F, pr)
                if ev is not None: cvp = np.where(SEA & ~ev, np.minimum(cvp, 2), cvp).astype(np.float32)   # دریا: بدون شاهد (بارش همرفتی همسایگی یا واداشت دینامیکی) سقف رده ۲
            out['cvp'] = cvp
    _SEA = g('sea') if hasattr(g('sea'), 'shape') else None
    capsea = (lambda a, lim: a) if (_SEA is None or cvp is None or CV_MODE != 'new') else (lambda a, lim: np.where(_SEA, np.minimum(a, lim), a).astype(np.float32))
    # ---- شدت همرفت: انرژی × برش + پتانسیل رگبار/تندباد پایین‌رو
    cb = None if (I['cape'] is None or I.get('s06') is None) else np.maximum(I['cape'], 0) * I['s06']
    wC15 = 0.15 if SW is None else np.where(SW, 0.15 * SEA_F if CV_MODE == 'new' else 0.03, 0.15).astype(np.float32)
    gust = g('gust')
    wCB, wSH, wPE = _sw(0.35), _sw(0.35), _sw(0.30)
    dbi = None if I.get('lr85') is None or I.get('spr700') is None else wavg([(0.5, nz(I['lr85'], 7.0, 9.0)), (0.5, nz(I['spr700'], 10, 25))])
    isc = wavg([(wCB, None if cb is None else nz(cb, 2500, 40000)), (wC15, None if I['cape'] is None else nz(np.maximum(I['cape'], 0), 500, 3000)),
                (0.15, None if I.get('s06') is None else nz(I['s06'], 10, 25)), (0.10, None if I.get('s85') is None else nz(I['s85'], 5, 18)),
                (0.15, None if gust is None else nz(gust, 40, 100)), (0.10, dbi)])
    cvi = None
    if isc is not None and cvp is not None:
        cvi = np.where(cvp >= 1, cls(np.clip(isc, 0, 1), [0.15, 0.30, 0.45, 0.60, 0.75]), 0).astype(np.float32); cvi = np.where(np.isnan(isc) | np.isnan(cvp), np.nan, cvi); cvi = capsea(cvi, np.minimum(cvp + 1, 5)); out['cvi'] = cvi
    # ---- تگرگ: SHIP + عمق ناحیهٔ رشد + تراز انجماد + CAPE بهینه + لپس‌ریت + برش
    hail = None
    if I['cape'] is not None and I.get('s06') is not None and I.get('lr75') is not None and I.get('mr') is not None and g('t500') is not None:
        r = np.clip(I['mr'], 11.0, 13.6); sh = np.clip(I['s06'], 7.0, 27.0); t5 = -np.minimum(g('t500'), -5.5)
        ship = np.maximum(I['cape'], 0) * r * I['lr75'] * t5 * sh / 42e6
        ship = np.where(I['cape'] < 1300, ship * np.maximum(I['cape'], 0) / 1300.0, ship); ship = np.where(I['lr75'] < 5.8, ship * np.maximum(I['lr75'], 0) / 5.8, ship)
        if I.get('fzl') is not None: ship = np.where(I['fzl'] < 2400, ship * np.maximum(I['fzl'], 0) / 2400.0, ship)
        if CV_MODE != 'new' and SW is not None: ship = np.where(SW, np.nan, ship).astype(np.float32)
        hs = wavg([(wSH, nz(ship, 0.0, 2.0)),
                   (0.15, None if I.get('hgz') is None else nz(I['hgz'], 1200, 3200)),
                   (0.10, None if I.get('fzl') is None else nz(I['fzl'], 4800, 2800)),
                   (wC15, nz(np.maximum(I['cape'], 0), 400, 2200)), (0.10, nz(I['lr75'], 6.0, 8.0)), (0.15, nz(I['s06'], 8, 22))])
        hs = np.where(I['s06'] < 8, hs * 0.6, hs)                                              # برش کم → رگبار تک‌سلولی، تگرگ درشت کم‌احتمال
        hail = np.where(cvp >= 1, cls(np.clip(hs, 0, 1), [0.12, 0.25, 0.40, 0.55, 0.70]), 0) if cvp is not None else cls(np.clip(hs, 0, 1), [0.12, 0.25, 0.40, 0.55, 0.70])
        hail = np.where(np.isnan(hs), np.nan, hail).astype(np.float32)
        if cvp is not None: hail = capsea(hail, cvp)                                            # دریا: تگرگ بیش از پتانسیل همرفت نمی‌شود
        out['hail'] = hail
    # ---- آذرخش: CAPE×بارش (Romps) + LI + ناحیهٔ مخلوط‌فاز + رطوبت
    ltg = None
    if I['cape'] is not None:
        pe = None if pr is None else np.maximum(I['cape'], 0) * np.maximum(pr, 0)
        if CV_MODE != 'new' and pe is not None and SW is not None: pe = np.where(SW, np.nan, pe).astype(np.float32)
        ls = wavg([(wPE, None if pe is None else nz(np.log10(1 + pe), np.log10(21), np.log10(2001))), (wC, nz(np.maximum(I['cape'], 0), 100, 2500)),
                   (_sw(0.15), None if I.get('li') is None else nz(I['li'], 2.0, -6.0)), (0.15, None if I.get('hgz') is None else nz(I['hgz'], 1000, 3500)),
                   (0.10, None if I.get('pw') is None else nz(I['pw'], 10, 35)), (0.10, None if I.get('tt') is None else nz(I['tt'], 46, 56))])
        ltg = np.where((I['cape'] >= 100) | ((CV_MODE != 'new') & (False if SW is None else SW)), cls(np.clip(ls, 0, 1), [0.15, 0.30, 0.45, 0.60, 0.75]), 0); ltg = np.where(np.isnan(ls) | np.isnan(I['cape']), np.nan, ltg).astype(np.float32)
        if cvp is not None: ltg = capsea(ltg, np.minimum(cvp + 1, 5))                          # دریا: آذرخش حداکثر یک رده بالاتر از پتانسیل همرفت
        out['ltg'] = ltg
    # ---- سیل‌خیزی
    fl = None; rain = None
    for k, lo, hi in (('p1', 10, 50), ('p3', 20, 80), ('p6', 30, 110), ('p12', 40, 150), ('p24', 40, 180)):
        if g(k) is not None: a = nz(np.maximum(g(k), 0), lo, hi); rain = a if rain is None else np.fmax(rain, a)
    if rain is not None:
        susc = 1.0 + 0.20 * np.nan_to_num(nz(g('slope'), 0.5, 5.0)) if g('slope') is not None else 1.0
        wet = 0.25 * np.nan_to_num(nz(g('soil'), 0.10, 0.35), nan=0.4) if g('soil') is not None else 0.1
        fl = cls(np.clip(rain * (susc + wet), 0, 1.2), [0.25, 0.45, 0.65, 0.85]); out['flood'] = fl
    # ---- هشدارها (سطح ۰..۳)
    def L(x, th): return None if x is None else cls(x, th)
    W = {}
    r6 = L(g('p6'), [20, 40, 70]); r24 = L(g('p24'), [40, 80, 140]); W['wrain'] = mx(r6, r24)
    rl = mx(L(g('p6'), [5, 12, 25]), L(g('p24'), [10, 25, 50]))                               # بارش با شدت: زرد ≥۵ mm/۶ساعت یا ≥۱۰ mm/۲۴ساعت، نارنجی ≥۱۲ یا ≥۲۵، قرمز ≥۲۵ یا ≥۵۰ (سنگین‌تر از این در «بارش سنگین»)
    if rl is not None:
        liquid = (g('t2') > 1.0) if g('t2') is not None else True                              # برف در هشدار برف می‌آید
        W['wrainl'] = np.where(liquid, rl, 0).astype(np.float32) * np.where(np.isnan(rl), np.nan, 1)
    W['wsnow'] = mx(L(g('sn6'), [3, 8, 15]), L(g('sn24'), [5, 15, 30]))
    if g('iceprec') is not None and pr is not None: W['wice'] = np.where(g('iceprec') > 0.5, cls(pr, [0.1, 0.5, 2.0]), 0).astype(np.float32)
    elif g('t2') is not None and pr is not None and g('t850') is not None:
        W['wice'] = np.where((g('t2') > -4) & (g('t2') < 0.5) & (g('t850') > 0.5) & (pr >= 0.2), 1, 0).astype(np.float32)
    W['wwind'] = L(gust, [50, 75, 100])
    if gust is not None and g('rh2') is not None:
        dry = (g('rh2') < 45) & ((g('soil') < 0.15) if g('soil') is not None else True) & ((pr < 0.1) if pr is not None else True)
        W['wdust'] = np.where(dry, cls(gust, [45, 60, 80]), 0).astype(np.float32)
    if g('vis') is not None: W['wfog'] = cls(-g('vis'), [-1000, -500, -200])
    elif g('rh2') is not None and g('ws10') is not None:
        W['wfog'] = np.where((g('rh2') >= 99) & (g('ws10') < 2), 2, np.where((g('rh2') >= 97) & (g('ws10') < 3) & ((pr < 0.1) if pr is not None else True), 1, 0)).astype(np.float32)
    t2 = g('t2c') if g('t2c') is not None else g('t2')
    if t2 is not None:
        W['wfrost'] = cls(-t2, [0, 5, 10])
        cloud = g('cloud') if g('cloud') is not None else (np.clip((g('rh2') - 50) / 40, 0, 1) * 100 if g('rh2') is not None else np.full(np.shape(t2), 30.0, np.float32))
        wsv = g('ws10') if g('ws10') is not None else np.full(np.shape(t2), 2.0, np.float32)
        dT = (1.5 + 3.0 * (1 - np.clip(cloud, 0, 100) / 100)) * (1 - 0.6 * np.clip((wsv - 1) / 5, 0, 1))             # کاهش دمای تابشی چمن نسبت به ۲ متر
        tg = g('tskin') if g('tskin') is not None else t2 - dT
        W['wgfrost'] = cls(-tg, [0.0, 3.0, 6.0])
        if g('ws10') is not None:
            v = np.maximum(g('ws10') * 3.6, 4.8); wct = 13.12 + 0.6215 * t2 - 11.37 * v ** 0.16 + 0.3965 * t2 * v ** 0.16
            W['wcold'] = np.where((t2 <= 10) & (g('ws10') * 3.6 >= 4.8), cls(-wct, [10, 28, 40]), 0).astype(np.float32)
        if g('rh2') is not None:
            td = td_from_rh(t2, g('rh2')); e = g('rh2') / 100.0 * es(t2); ws0 = g('ws10') if g('ws10') is not None else 1.0
            at = t2 + 0.33 * e - 0.70 * ws0 - 4.0
            W['wheat'] = cls(np.fmax(t2, at), [40, 45, 50]); W['whum'] = np.where(t2 >= 28, cls(td, [22, 24, 26]), 0).astype(np.float32)
        else: W['wheat'] = cls(t2, [40, 45, 50])
    if cvp is not None:
        W['wtstm'] = mx(np.where(cvp >= 5, 3, np.where(cvp >= 4, 2, np.where(cvp >= 3, 1, 0))).astype(np.float32) * np.where(np.isnan(cvp), np.nan, 1),
                        None if cvi is None else np.where(cvi >= 5, 3, np.where(cvi >= 4, 2, np.where(cvi >= 3, 1, 0))).astype(np.float32) * np.where(np.isnan(cvi), np.nan, 1))
    if hail is not None: W['whail'] = np.where(hail >= 4, 3, np.where(hail >= 3, 2, np.where(hail >= 2, 1, 0))).astype(np.float32) * np.where(np.isnan(hail), np.nan, 1)
    if ltg is not None: W['wltg'] = np.where(ltg >= 5, 3, np.where(ltg >= 4, 2, np.where(ltg >= 3, 1, 0))).astype(np.float32) * np.where(np.isnan(ltg), np.nan, 1)
    if fl is not None: W['wflood'] = np.where(fl >= 4, 3, np.where(fl >= 3, 2, np.where(fl >= 2, 1, 0))).astype(np.float32) * np.where(np.isnan(fl), np.nan, 1)
    p3 = g('p3') if g('p3') is not None else g('p1')
    if p3 is not None:
        lv = cls(np.maximum(p3, 0), [20, 35, 55]); flat = (np.nan_to_num(g('slope'), nan=0.0) < 1.5) if g('slope') is not None else True
        W['wlog'] = np.where(flat, lv, np.maximum(lv - 1, 0)).astype(np.float32)
    # دریا: خطرهای «مخصوص خشکی/انسان» (گرمای محسوس، شرجی، یخبندان، سوزباد، گردوغبار از خاک، سیل و آبگرفتگی) روی یاخته‌های دریا صفر می‌شوند؛
    # باد، بارش، توفان تندری، تگرگ، آذرخش و مه روی دریا می‌مانند. مثلاً نقطهٔ شبنم ≥۲۴ در خلیج فارس/دریای عمان در پاییز عادی است و هشدار شرجی نیست.
    _S = g('sea') if hasattr(g('sea'), 'shape') else None
    if _S is not None:
        for k in ('wheat', 'whum', 'wfrost', 'wgfrost', 'wcold', 'wdust', 'wflood', 'wlog'):
            if W.get(k) is not None: W[k] = np.where(_S, 0, W[k]).astype(np.float32)
    for k, v in W.items():
        if v is not None: out[k] = v.astype(np.float32)
    allw = [W[k] for k in W if W[k] is not None]
    if allw:
        m = allw[0]
        for a in allw[1:]: m = np.fmax(m, a)
        out['warn'] = m.astype(np.float32)
    return out

def mx(a, b): return b if a is None else (a if b is None else np.fmax(a, b))

# ---------------------------------------------------------------- تجمیع پنجره‌ای
def end6(vt): return (vt + timedelta(hours=(3 - vt.hour) % 6)).replace(minute=0, second=0, microsecond=0)
def end24(vt): return (vt + timedelta(hours=(21 - vt.hour) % 24)).replace(minute=0, second=0, microsecond=0)

class SecAcc:
    """بیشینهٔ هر خطر در پنجره‌های ۶ ساعته، ۲۴ ساعته و تجمعی (فقط پایان‌های ۲۱ UTC، برای کم‌کردن حجم).
    پنجرهٔ ناقص (شروع پیش از ابتدای اجرا) منتشر نمی‌شود؛ اگر گام‌های مدل کمیاب‌تر از پنجره باشند با گام‌های موجود ساخته می‌شود."""
    def __init__(s, run, maxlead=384):
        s.run, s.maxlead = run, maxlead; s.w = {'6': {}, '24': {}}; s.cum = {}; s.done = set(); s.cum_next = None
    def _first(s): return end24(s.run + timedelta(seconds=1))
    def pre(s, vt):
        res = []
        for k, wd in (('6', 6), ('24', 24)):
            for e in sorted(e for e in s.w[k] if e < vt):
                d = s.w[k].pop(e)
                if e - timedelta(hours=wd) >= s.run and (k, e) not in s.done: s.done.add((k, e)); res.append((k, e, d))
        e = s._first() if s.cum_next is None else s.cum_next
        while e < vt and (e - s.run).total_seconds() / 3600 <= s.maxlead:
            if s.cum: res.append(('acc', e, dict(s.cum)))
            e += timedelta(hours=24)
        s.cum_next = e
        return res
    def add(s, vt, H):
        for key, e in (('6', end6(vt)), ('24', end24(vt))):
            d = s.w[key].setdefault(e, {})
            for h, a in H.items(): d[h] = a if h not in d else np.fmax(d[h], a)
        for h, a in H.items(): s.cum[h] = a if h not in s.cum else np.fmax(s.cum[h], a)
    def post(s, vt):
        res = []; e6, e24 = end6(vt), end24(vt)
        if vt == e6 and e6 in s.w['6']:
            d = s.w['6'].pop(e6)
            if e6 - timedelta(hours=6) >= s.run and ('6', e6) not in s.done: s.done.add(('6', e6)); res.append(('6', e6, d))
        if vt == e24 and e24 in s.w['24']:
            d = s.w['24'].pop(e24)
            if e24 - timedelta(hours=24) >= s.run and ('24', e24) not in s.done: s.done.add(('24', e24)); res.append(('24', e24, d))
        e = s._first() if s.cum_next is None else s.cum_next
        if e == vt and 0 < (vt - s.run).total_seconds() / 3600 <= s.maxlead and s.cum:
            res.append(('acc', vt, dict(s.cum))); s.cum_next = e + timedelta(hours=24)
        elif s.cum_next is None: s.cum_next = e
        return res

def selftest():
    n = (40, 50); r = np.random.default_rng(1); U = lambda a, b: r.uniform(a, b, n).astype(np.float32)
    F = dict(cape=U(0, 4000), cin=-U(0, 300), rh850=U(20, 100), rh700=U(20, 100), rh500=U(20, 100), rh925=U(20, 100), rh300=U(10, 80), u10=U(-5, 5), v10=U(-5, 5), u500=U(0, 20), v500=U(-10, 10),
             u850=U(-5, 10), v850=U(-5, 10), t925=U(10, 28), t850=U(5, 25), t700=U(-5, 10), t500=U(-25, -8), t300=U(-50, -35), t2=U(-12, 46), rh2=U(10, 100), ps=U(800, 1010), zs=U(0, 2500), pr=U(0, 12),
             gust=U(10, 120), p1=U(0, 40), p3=U(0, 80), p6=U(0, 100), p12=U(0, 120), p24=U(0, 200), sn6=U(0, 10), sn24=U(0, 40), ws10=U(0, 12), slope=U(0, 8), soil=U(0.05, 0.4), pw=U(2, 40), cloud=U(0, 100))
    H = hazards(F)
    for k in HAZ:
        assert k in H, k; a = H[k]; assert a.shape == n and np.nanmin(a) >= 0 and np.nanmax(a) <= len(SECSC[PRODUCTS[k][2]]['colors']) - 1, (k, np.nanmax(a))
    # با میدان‌های ناقص هم نباید خطا بدهد
    F2 = {k: v for k, v in F.items() if k in ('p6', 'p24', 'gust', 't2', 'rh2', 'ws10')}
    H2 = hazards(F2); assert 'wrain' in H2 and 'wwind' in H2 and 'wheat' in H2 and 'cvp' not in H2
    return {k: (float(np.nanmin(v)), float(np.nanmax(v))) for k, v in H.items()}

if __name__ == '__main__':
    print(selftest())

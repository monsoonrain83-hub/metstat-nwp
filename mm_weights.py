# -*- coding: utf-8 -*-
"""MetStat MultiModel (مالتی مدل MetStat) — وزن‌دهی مدل‌ها.

وزن‌های پایه طبق دستور کاربر؛ بر اساس فصل (تاریخ شمسی) و گروه پارامتر.
اگر مدلی پارامتر/گام زمانی را ندارد، از ترکیب حذف و وزن بقیه به تناسب وزن پایه‌شان بازتوزیع می‌شود:
    w_i = base_i / Σ_{j ∈ موجود} base_j
NAVGEM هرگز در ترکیب نیست.
"""
from datetime import date, datetime

# شناسهٔ مدل‌ها در nwp_maps.py: اروپا=ecmwf (۲۸ کیلومتر)، آمریکا=gfs (۱۳ کیلومتر؛ در نبود آن gfs25)،
# آلمان=icon، کانادا=gem، بریتانیا=ukmo، فرانسه=arpege
MM_MODELS = ('ecmwf', 'gfs', 'icon', 'gem', 'ukmo', 'arpege')
EXCLUDED = ('navgem', 'access')                     # در ترکیب دخالت نمی‌کنند
# هر «اسلات» از چند منبع به ترتیب اولویت پر می‌شود: اروپا ← ۹ کیلومتر تا هر گامی که دارد، وگرنه ۲۸ کیلومتر؛ آمریکا ← ۱۳ کیلومتر وگرنه ۲۸
SLOT_SRC = {'ecmwf': ('ecmwf9', 'ecmwf'), 'gfs': ('gfs', 'gfs25')}


def pick_sources(available):
    """از مدل‌های آماده، برای هر اسلات بهترین منبع را برمی‌گرداند: {اسلات: شناسهٔ مدل واقعی}."""
    av = set(available); out = {}
    for m in MM_MODELS:
        for src in SLOT_SRC.get(m, (m,)):
            if src in av: out[m] = src; break
    return out

FA = {'ecmwf': 'اروپا (ECMWF)', 'gfs': 'آمریکا (GFS)', 'icon': 'آلمان (ICON)', 'gem': 'کانادا (GEM)',
      'ukmo': 'بریتانیا (UKMO)', 'arpege': 'فرانسه (ARPEGE)'}
EN = {'ecmwf': 'ECMWF', 'gfs': 'GFS', 'icon': 'ICON', 'gem': 'GEM', 'ukmo': 'UKMO', 'arpege': 'ARPEGE'}

# فصل سرد: ۵ آبان تا ۳۱ اردیبهشت — فصل گرم: ۱ خرداد تا ۴ آبان
BASE = {
    ('cold', 'general'):    {'ecmwf': 40, 'gfs': 30, 'icon': 10, 'gem': 10, 'ukmo': 5, 'arpege': 5},
    ('cold', 'convection'): {'gfs': 45, 'ecmwf': 30, 'icon': 10, 'gem': 10, 'arpege': 5},
    ('warm', 'general'):    {'gem': 45, 'gfs': 25, 'ecmwf': 15, 'icon': 10, 'ukmo': 5},
    ('warm', 'convection'): {'gfs': 45, 'gem': 30, 'icon': 10, 'ecmwf': 10, 'arpege': 5},
}

# گروه پارامتر → دستهٔ وزن. (باد و دما: همهٔ سال با وزن‌های عمومی فصل سرد.)
GROUPS = ('precip', 'snow', 'temp', 'humidity', 'convection', 'wind', 'pressure', 'sigwx')
GROUP_FA = {'precip': 'بارش', 'snow': 'برف', 'temp': 'دما', 'humidity': 'رطوبت', 'convection': 'همرفت',
            'wind': 'باد', 'pressure': 'فشار و ترازهای بالا', 'sigwx': 'هوای مهم'}
WEIGHT_CLASS = {g: ('convection' if g == 'convection' else 'general') for g in GROUPS}


def jalali_from_gregorian(gy, gm, gd):
    """تبدیل میلادی به شمسی (الگوریتم jalaali)؛ خروجی (سال، ماه، روز)."""
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = 355666 + 365 * gy + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400 + gd + g_d_m[gm - 1]
    jy = -1595 + 33 * (days // 12053); days %= 12053
    jy += 4 * (days // 1461); days %= 1461
    if days > 365: jy += (days - 1) // 365; days = (days - 1) % 365
    if days < 186: jm = 1 + days // 31; jd = 1 + days % 31
    else: jm = 7 + (days - 186) // 30; jd = 1 + (days - 186) % 30
    return jy, jm, jd


def season(d):
    """'warm' برای ۱ خرداد…۴ آبان، وگرنه 'cold' (۵ آبان…۳۱ اردیبهشت). d: date یا datetime (UTC)."""
    _, m, dd = jalali_from_gregorian(d.year, d.month, d.day)
    return 'warm' if (3, 1) <= (m, dd) <= (8, 4) else 'cold'


ALL_YEAR_COLD = ('wind', 'temp')     # باد و دما: همهٔ سال با وزن‌های فصل سرد (دستور کاربر)


def base_weights(group, d):
    s = 'cold' if group in ALL_YEAR_COLD else season(d); return dict(BASE[(s, WEIGHT_CLASS[group])]), s


def weights(group, d, available):
    """وزن نهایی مدل‌ها (جمع = ۱). available: مدل‌هایی که این پارامتر/گام را دارند و فیلدشان آماده است.
    خروجی: (dict مدل→وزن, فصل, مدل‌های حذف‌شده از وزن پایه)."""
    base, s = base_weights(group, d)
    av = [m for m in pick_sources(available) if m in base and m not in EXCLUDED]
    tot = float(sum(base[m] for m in av))
    if tot <= 0: return {}, s, sorted(base)
    return {m: base[m] / tot for m in av}, s, sorted(m for m in base if m not in av)


def caption(w, lang='fa'):
    """متن زیر نقشه: مدل‌های مشارکت‌کننده و وزن‌ها."""
    ms = sorted(w, key=lambda m: -w[m])
    if lang == 'fa':
        return 'ترکیب وزنی مدل‌ها: ' + '، '.join(f'{FA[m]} {round(w[m]*100):d}٪' for m in ms)
    return 'Weighted blend of: ' + ', '.join(f'{EN[m]} {round(w[m]*100)}%' for m in ms)


# ---- نگاشت شناسهٔ پارامترهای nwp_maps.py به گروه
def group_of(pid):
    p = str(pid)
    if p in ('p1', 'p3', 'p6', 'p24', 'p48', 'p120', 'pacc'): return 'precip'
    if p in ('s1', 's3', 's6', 'snow24', 's48', 's120', 'snowacc'): return 'snow'
    if p in ('t2m', 'tmax', 'tmin', 'tanom'): return 'temp'
    if p in ('rh', 'pw'): return 'humidity'
    if p in ('ki', 'cape', 'si', 'gdi', 'refl', 'li', 'cin', 'tt', 'ko', 'shw', 'lr75', 'lr85', 'sh06', 'sh85', 'swt', 'fzl', 'hgz'): return 'convection'
    if p in ('gust', 'w500', 'w300'): return 'wind'
    if p in ('sfc', 'z850', 'z700', 'z500'): return 'pressure'
    if p == 'sigwx': return 'sigwx'
    return None            # بقیه (مثلاً نقشه‌های ثانویهٔ همرفت/آذرخش) در گام بعد بر اساس haz تعیین می‌شوند


# ---- نقشه‌های ثانویه (خطرها/هشدارها): گروه وزن بر اساس نوع خطر (haz)؛ میدان‌ها رده‌ای (۰..۵) هستند و پس از میانگین وزنی به نزدیک‌ترین رده گرد می‌شوند
HAZ_GROUP = {'cvp': 'convection', 'cvi': 'convection', 'hail': 'convection', 'ltg': 'convection', 'wtstm': 'convection', 'whail': 'convection', 'wltg': 'convection',
             'flood': 'precip', 'wflood': 'precip', 'wlog': 'precip', 'wrain': 'precip', 'wrainl': 'precip', 'wsnow': 'precip', 'wice': 'precip',
             'wwind': 'wind', 'wdust': 'wind', 'wfrost': 'temp', 'wgfrost': 'temp', 'wcold': 'temp', 'wheat': 'temp', 'whum': 'temp', 'wfog': 'humidity', 'warn': 'precip'}


# ---- نقشه‌های بیشینه/کمینهٔ مدل‌ها (بدون وزن؛ همه مدل‌های موجود)
MINMAX = {
    'p24': ('max', 'min'), 'pacc': ('max', 'min'), 'snow24': ('max', 'min'), 'snowacc': ('max', 'min'),
    'gust': ('max',), 'tmax': ('max',), 'tmin': ('min',),
}

if __name__ == '__main__':
    for s_, d_ in (('cold', date(2026, 12, 1)), ('warm', date(2026, 7, 1))):
        for g in ('precip', 'convection'):
            w, s, miss = weights(g, d_, MM_MODELS); print(s_, g, {k: round(v, 3) for k, v in w.items()})

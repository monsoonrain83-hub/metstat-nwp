# -*- coding: utf-8 -*-
"""
MetStat — ساخت خودکار نقشه‌های مدل‌های عددی (ECMWF، GFS، ICON، UKMO، GEM) برای «تحلیل نقشه‌های آنلاین»

منبع داده: داده‌های باز مدل‌ها در Open-Meteo روی Amazon S3 (s3://openmeteo/data_spatial، مجوز CC-BY 4.0) با بهترین
رزولوشن رایگان هر مدل. هر گام زمانی به‌محض انتشار خوانده می‌شود (فقط محدودهٔ ایران)، پارامترهای مشتق (شاخص K، GDI،
Lifted، Soaring، بازتاب، هوای مهم، انومالی دما…) محاسبه و نقشه با قاب و رنگ‌بندی weather.us (رنگ‌های گسسته، بدون رنگ
واسطه) ساخته و با HTTPS به هاست (online/nwp_upload.php) فرستاده می‌شود. با شروع اجرای جدید هر مدل، اجرای قبلی همان
مدل روی هاست پاک می‌شود.

اجرا:
    pip install "omfiles[fsspec]" s3fs requests numpy scipy pillow matplotlib
    python nwp_maps.py --host https://wtafkik.ir/online --key کلید_آپلود --loop --max-minutes 340
آزمون بدون اینترنت (دادهٔ ساختگی، خروجی در پوشهٔ out):  python nwp_maps.py --mock --out out --models ecmwf --max-steps 6
"""
import argparse, functools, io, json, math, os, sys, time, threading, traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import numpy as np
from scipy.ndimage import map_coordinates, gaussian_filter
from PIL import Image, ImageDraw, ImageFont
import styles, secondary, warn_icons, id_points, wind_tile, hl_centers
styles.SC.update(secondary.SECSC)

UTC = timezone.utc
HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, 'assets') if os.path.isdir(os.path.join(HERE, 'assets')) else HERE   # پوشهٔ assets یا کنار همین فایل
def log(s): print(datetime.now(UTC).strftime('%H:%M:%S ') + s, flush=True)

# ---------------------------------------------------------------- مدل‌ها و شبکه‌ها
# (nx, ny, latMin, lonMin, dx, dy) — همان تعریف سرور Open-Meteo
GRIDS = {
    'ecmwf_ifs025': (1440, 721, -90, -180, 0.25, 0.25),
    'ecmwf_ifs': (3600, 1801, -90, -180, 0.1, 0.1),        # HRES ۹ کیلومتری (فرض: شبکهٔ منظم ۰٫۱°؛ اگر فایل واقعی فرق داشته باشد در لاگ «شبکهٔ … با تعریف فرق دارد» چاپ و مدل کنار گذاشته می‌شود)
    'ncep_gfs013': (3072, 1536, -0.11714935 * 1535 / 2, -180, 360 / 3072, 0.11714935),
    'ncep_gfs025': (1440, 721, -90, -180, 0.25, 0.25),
    'dwd_icon': (2879, 1441, -90, -180, 0.125, 0.125),
    'dwd_icon_eu': (1377, 657, 29.5, -23.5, 0.0625, 0.0625),
    'ukmo_global_deterministic_10km': (2560, 1920, -90, -180, 360 / 2560, 180 / 1920),
    'cmc_gem_gdps_15km': (2400, 1201, -90, -180, 0.15, 0.15),
    'cmc_gem_gdps': (2400, 1201, -90, -180, 0.15, 0.15),
}
BBOX = (-14.0, 70.0, 8.0, 64.0)        # lon0, lon1, lat0, lat1 — r66: بزرگ شد تا کادر «اروپا» (EU_EXT) هم داده داشته باشد (قبلاً ۱۷..۶۸E و ۹..۴۵N بود و اروپا نوار می‌شد)
ME_EXT = (20.0, 65.0, 12.0, 42.0)      # کادر «خاورمیانه» نمایشگر (همان کادر Tropical Tidbits)
PXD = 32                                # پیکسل در هر درجه برای کاشی‌های خاورمیانه (≈ ۰٫۰۳ درجه)
MEW, MEH = int((ME_EXT[1] - ME_EXT[0]) * PXD), int((ME_EXT[3] - ME_EXT[2]) * PXD)
# r65: کادر «اروپا» (فقط ترازهای بالا و فشار سطح دریا): اروپا، غرب روسیه، شمال کاسپین، مصر/لیبی و بخشی از دریای عرب
EU_EXT = (-12.0, 68.0, 12.0, 62.0); EU_PXD = 16
EUW, EUH = int((EU_EXT[1] - EU_EXT[0]) * EU_PXD), int((EU_EXT[3] - EU_EXT[2]) * EU_PXD)
EU_PIDS = ('z850', 'z700', 'z500', 'z500a', 'w500', 'w300', 'w250', 'w200', 'sfc', 'w10')
MODELS = {
    'ecmwf':  dict(name='ECMWF 28km', label='ECMWF IFS 28km (0.25°)', dom=['ecmwf_ifs025'], prov='ECMWF', hz={'00': 360, '12': 360, '06': 144, '18': 144}, res='0.25°', cyc='00/12', only_cyc=(0, 12)),
    'ecmwf9': dict(name='ECMWF 9km', label='ECMWF IFS 9km (HRES)', dom=['ecmwf_ifs'], prov='ECMWF', hz={'00': 240, '12': 240, '06': 144, '18': 144}, res='0.1° (9 km)', cyc='00/12', only_cyc=(0, 12)),   # فقط پارامترهای سطحی؛ ترازهای فشاری در HRES نیست
    'gfs':    dict(name='GFS 13km', label='GFS 13km (0.11°)', dom=['ncep_gfs013'], upper='ncep_gfs025', prov='NOAA NCEP', hz=384, res='0.11° (13 km)', cyc='00/06/12/18'),
    'gfs25':  dict(name='GFS 28km', label='GFS 28km (0.25°)', dom=['ncep_gfs025'], prov='NOAA NCEP', hz=384, res='0.25° (28 km)', cyc='00/06/12/18'),
    'icon':   dict(name='ICON', label='ICON-EU 7 km + ICON 13 km', dom=['dwd_icon'], hires='dwd_icon_eu', prov='DWD', hz={'00': 180, '12': 180, '06': 120, '18': 120}, res='7 km (اروپا) / 13 km', cyc='00/06/12/18'),
    'ukmo':   dict(name='UKMO', label='UKMO Global 10 km', dom=['ukmo_global_deterministic_10km'], prov='Met Office', hz=168, res='10 km', cyc='00/06/12/18'),
    'gem':    dict(name='GEM', label='GEM GDPS 15 km', dom=['cmc_gem_gdps_15km', 'cmc_gem_gdps'], prov='ECCC', hz=240, res='15 km', cyc='00/12'),
}
# r83: حذف اختیاری مدل از تولید (فضای هاست): NWP_DROP_MODELS=arpege  (پیش‌فرض: هیچ‌کدام). پوشهٔ قدیمی را روی هاست دستی پاک کنید.
for _m in [x.strip() for x in os.environ.get('NWP_DROP_MODELS', '').split(',') if x.strip()]: MODELS.pop(_m, None)
REGIONS = {'iran': dict(geo=(-1506.432, 35.07327, 1611.463, -40.47955), en='Iran', fa='ایران'),
           'fars': dict(geo=(-4387.15, 89.808, 3366.55, -103.991), en='Fars', fa='فارس')}
FX0, FX1, FY0, FY1 = 2, 757, 2, 614
W = H = 760

# ---------------------------------------------------------------- پارامترها
ALL = [m for m in MODELS if m != 'ecmwf9']      # ecmwf9 فقط پارامترهای سطحی انتخاب‌شده را می‌سازد
PR_WIN = [  # (id, ساعت پنجره، بازهٔ ساعت پایان، تا چه ساعتی، نوع نوار)
    ('p1', 1, 1, 72, 'h1'), ('p3', 3, 3, 144, 'h24'), ('p6', 6, 6, 999, 'h24'), ('p24', 24, 6, 999, 'h24'),
    ('p48', 48, 24, 999, 'h24'), ('p120', 120, 24, 999, 'h24'), ('pacc', 0, 6, 999, 'h24')]
SN_WIN = [('s1', 1, 1, 72, 'h1'), ('s3', 3, 3, 144, 'h24'), ('s6', 6, 6, 999, 'h24'), ('snow24', 24, 6, 999, 'h24'),
          ('s48', 48, 24, 999, 'acc'), ('s120', 120, 24, 999, 'acc'), ('snowacc', 0, 6, 999, 'acc')]
PARAMS = {}
FAD = str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹')
for pid, hh, ev, mx, v in PR_WIN:
    PARAMS[pid] = dict(kind='win', var='precip', h=hh, every=ev, maxlead=mx, sc='pr_' + v, wv=v, models=ALL, unit='mm',
                       en=(f'Precipitation, {hh}h (mm)' if hh else 'Total precipitation (mm)'),
                       fa=(f'بارش {hh} ساعته'.translate(FAD) if hh else 'بارش تجمعی از ابتدای اجرا'))
for pid, hh, ev, mx, v in SN_WIN:
    PARAMS[pid] = dict(kind='win', var='snow', h=hh, every=ev, maxlead=mx, sc='pr_' + v, wv=v, models=ALL, unit='mm', skip_empty=True,
                       en=(f'Snowfall (water equivalent), {hh}h (mm)' if hh else 'Total snowfall (water equivalent) (mm)'),
                       fa=(f'بارش برف {hh} ساعته (آب معادل)'.translate(FAD) if hh else 'برف تجمعی (آب معادل)'))
I_EC = ['ecmwf']; I_ECA = ['ecmwf']; I_ECG = ['ecmwf', 'gfs', 'gfs25']
I_CV = ['ecmwf', 'gfs', 'gfs25', 'icon', 'ukmo']      # مدل‌هایی که CAPE دارند (نتیجهٔ probe)؛ شاخص‌های ترازی از ترازهای فشاری همان مدل
PARAMS.update({
    't2m':   dict(kind='inst', sc='temp', models=I_ECA, unit='°C', en='Temperature 2m (°C)', fa='دمای ۲ متری', lapse=True),
    'tsoil': dict(kind='inst', sc='temp', models=I_ECA, unit='°C', en='Soil temperature near surface (°C)', fa='دمای خاک نزدیک سطح'),
    'tmax':  dict(kind='day', sc='temp', models=I_ECA, unit='°C', en='Max. temperature 2m, 24h (°C)', fa='دمای بیشینه ۲۴ ساعته', lapse=True),
    'tmin':  dict(kind='day', sc='temp', models=I_ECA, unit='°C', en='Min. temperature 2m, 24h (°C)', fa='دمای کمینه ۲۴ ساعته', lapse=True),
    'tanom': dict(kind='day', sc='tanom', models=I_ECA, unit='K', en='Temperature 2m anomaly, daily mean (K)', fa='انومالی دمای ۲ متری (میانگین روزانه)', lapse=True),
    'rh':    dict(kind='inst', sc='rh', models=I_EC, unit='%', en='Relative humidity 2m (%)', fa='رطوبت نسبی ۲ متری'),
    'pw':    dict(kind='inst', sc='pw', models=I_EC, unit='mm', en='Entire Atmosphere Precipitable Water (mm)', fa='آب قابل بارش'),
    'ki':    dict(kind='inst', sc='ki', models=I_ECG, unit='', en='K-Index', fa='شاخص K'),
    'cape':  dict(kind='inst', sc='cape', models=I_ECG, unit='J/kg', en='CAPE (J/kg)', fa='CAPE'),
    'si':    dict(kind='inst', sc='si', models=I_ECG, unit='', en='Soaring Index', fa='شاخص سورینگ'),
    'gdi':   dict(kind='inst', sc='gdi', models=I_ECG, unit='', en='Galvez-Davison Index (GDI)', fa='شاخص گالوز-داویسون'),
    'refl':  dict(kind='inst', sc='refl', models=I_ECG, unit='dBZ', en='Base reflectivity (dBZ), from precip. rate', fa='بازتاب پایه (برآورد از شدت بارش)'),
    'li':    dict(kind='inst', sc='li', models=I_ECG, unit='K', en='Lifted Index (surface)', fa='شاخص صعود (Lifted)'),
    'sigwx': dict(kind='inst', sc='sigwx', models=I_ECG, unit='', en='Significant Weather', fa='هوای مهم'),
    'cin':   dict(kind='inst', sc='cin', models=['gfs', 'gfs25'], unit='J/kg', en='CIN (J/kg)', fa='CIN'),
    'gust':  dict(kind='inst', sc='gust', models=I_EC, unit='km/h', en='Wind gusts 10m (km/h)', fa='تندباد ۱۰ متری'),
    'sfc':   dict(kind='inst', sc='rh', models=I_EC, unit='%', en='MSLP (hPa), RH 2m (%) & wind 10m', fa='فشار سطح دریا، رطوبت و باد سطحی', cont='msl', barbs='10m'),
    'z850':  dict(kind='inst', sc='rh', models=I_EC, unit='%', en='Geopotential 850 hPa (gpdm) & RH 850 hPa (%)', fa='ارتفاع ژئوپتانسیل و رطوبت ۸۵۰ هکتوپاسکال', cont='gh850'),
    'z700':  dict(kind='inst', sc='rh', models=I_EC, unit='%', en='Geopotential 700 hPa (gpdm) & RH 700 hPa (%)', fa='ارتفاع ژئوپتانسیل و رطوبت ۷۰۰ هکتوپاسکال', cont='gh700'),
    'z500':  dict(kind='inst', sc='rh', models=I_EC, unit='%', en='Geopotential 500 hPa (gpdm) & RH 500 hPa (%)', fa='ارتفاع ژئوپتانسیل و رطوبت ۵۰۰ هکتوپاسکال', cont='gh500'),
    'w500':  dict(kind='inst', sc='windu', models=I_EC, unit='km/h', en='Wind 500 hPa (km/h)', fa='سرعت و جهت باد ۵۰۰ هکتوپاسکال', barbs='500hPa'),
    'w300':  dict(kind='inst', sc='windu', models=I_EC, unit='km/h', en='Wind 300 hPa (km/h)', fa='سرعت و جهت باد ۳۰۰ هکتوپاسکال', barbs='300hPa', me=dict(sc='windup', unit='kt', k=1.94384 / 3.6)),
})
# ---- نقشهٔ خود شاخص‌های ناپایداری/برش (از همان ورودی‌های نقشه‌های ثانویه)
SEC_IDX = {'tt': ('tt', 'tt', '', 'Total Totals Index', 'شاخص Total Totals'), 'ko': ('ko', 'ko', 'K', 'KO Index (surface-based)', 'شاخص KO (با تراز سطحی)'),
           'shw': ('show', 'shw', 'K', 'Showalter Index', 'شاخص Showalter'), 'lr75': ('lr75', 'lr', 'K/km', 'Lapse rate 700–500 hPa (K/km)', 'لپس‌ریت ۷۰۰–۵۰۰ هکتوپاسکال'),
           'lr85': ('lr85', 'lr', 'K/km', 'Lapse rate 850–500 hPa (K/km)', 'لپس‌ریت ۸۵۰–۵۰۰ هکتوپاسکال'), 'sh06': ('s06', 'shr', 'm/s', 'Bulk wind shear ~0–6 km (m/s)', 'برش باد ≈ ۰–۶ کیلومتر (m/s)'),
           'sh85': ('s85', 'shr', 'm/s', 'Bulk wind shear 850–500 hPa (m/s)', 'برش باد ۸۵۰–۵۰۰ هکتوپاسکال (m/s)'), 'swt': ('sweat', 'swt', '', 'SWEAT Index', 'شاخص SWEAT'),
           'fzl': ('fzl', 'fzl', 'm', 'Freezing level height above ground (m)', 'ارتفاع تراز صفر درجه از سطح زمین (m)'), 'hgz': ('hgz', 'hgz', 'm', 'Hail growth zone depth −10…−30°C (m)', 'عمق ناحیهٔ رشد تگرگ (−۱۰ تا −۳۰°C) (m)')}
# r81: لایه‌های همدیدی/جبهه‌ای سینرژی + ابر همرفتی روی صفحهٔ اول (همان موتور شاخص‌ها؛ با خطوط هم‌ارتفاع/هم‌فشار)
# r82: «لایه‌های سینرژی» در همهٔ ترازهای معنادار (همان فرمول مرورگر: تفاضل مرکزی روی شبکهٔ ژئودتیک؛ ۸۵۰ زیر سطح زمین ماسک)
_LV = {850: '۸۵۰', 700: '۷۰۰', 500: '۵۰۰', 300: '۳۰۰', 250: '۲۵۰', 200: '۲۰۰'}
SEC_IDX.update({'dte': ('dte', 'dte', 'K', 'Potential instability θe500 − θe850 (K)', 'ناپایداری پتانسیلی θe۵۰۰ − θe۸۵۰'),
    'thk': ('thk', 'thk', 'dam', '1000–500 hPa thickness (dam) & MSLP', 'ضخامت ۱۰۰۰–۵۰۰ هکتوپاسکال و فشار سطح دریا'),
    'mfc850': ('mfc850', 'mfc', 'g/kg/day', 'Moisture flux convergence 850 hPa (g/kg/day)', 'همگرایی شار رطوبت ۸۵۰ هکتوپاسکال'),
    'ccc': ('ccc', 'ccc', '%', 'Convective cloud cover (Slingo 1987) (%)', 'پوشش ابر همرفتی (روش Slingo)')})
for _l, _fa in _LV.items():
    SEC_IDX[f'vo{_l}'] = (f'vo{_l}', 'vo', '10⁻⁵ s⁻¹', f'Relative vorticity {_l} hPa (1e-5/s) & height', f'تاوایی نسبی {_fa} هکتوپاسکال و ارتفاع ژئوپتانسیل')
    SEC_IDX[f'dv{_l}'] = (f'dv{_l}', 'dv', '10⁻⁵ s⁻¹', f'Divergence {_l} hPa (1e-5/s)', f'واگرایی {_fa} هکتوپاسکال')
for _l in (850, 700, 500):
    SEC_IDX[f'ta{_l}'] = (f'ta{_l}', 'tadv', 'K/6h', f'Temperature advection {_l} hPa (K/6h)', f'فرارفت دمای {_LV[_l]} هکتوپاسکال (K در ۶ ساعت)')
for _l in (850, 700):
    SEC_IDX[f'te{_l}'] = (f'te{_l}', 'te', 'K', f'Equivalent potential temperature θe {_l} hPa (K)', f'دمای پتانسیل هم‌ارز θe {_LV[_l]} هکتوپاسکال')
    SEC_IDX[f'thw{_l}'] = (f'thw{_l}', 'thw', '°C', f'Wet-bulb potential temperature θw {_l} hPa (°C) — fronts', f'دمای پتانسیل تر θw {_LV[_l]} هکتوپاسکال (جبهه‌ها)')
    SEC_IDX[f'tw{_l}'] = (f'tw{_l}', 'thw', '°C', f'Wet-bulb temperature Tw {_l} hPa (°C)', f'دمای تر Tw {_LV[_l]} هکتوپاسکال')
for _l in (850, 700, 500, 300):
    SEC_IDX[f'w{_l}'] = (f'w{_l}', 'omg', 'Pa/s', f'Vertical velocity (omega) {_l} hPa (Pa/s)', f'سرعت قائم (امگا) {_LV[_l]} هکتوپاسکال')
_ZC = {850: (120, 165, 3), 700: (270, 330, 3), 500: (480, 600, 6), 300: (840, 980, 12), 250: (900, 1100, 12), 200: (1100, 1250, 12)}
SEC_CONT = {'thk': ('msl', 1.0, (960, 1052, 4)), 'mfc850': ('z850', 10.0, (120, 165, 3))}
for _l, _r in _ZC.items():
    for _q in ('vo', 'dv', 'w'): SEC_CONT[f'{_q}{_l}'] = (f'z{_l}', 10.0, _r)
    for _q in ('ta', 'te', 'thw', 'tw'): SEC_CONT[f'{_q}{_l}'] = (f'z{_l}', 10.0, _r)
# r83: لایه‌های سینرژی روی صفحهٔ اصلی منتشر نمی‌شوند (فضای هاست)؛ فقط در تب سینرژی‌اند و در نقشه‌های ثانویه مشارکت می‌کنند (secondary.py).
#      برای انتشار دوباره: متغیر محیطی NWP_PUBLISH_DY=all  یا  فهرست جداشده با کاما مثل vo500,dv300
_PUB = os.environ.get('NWP_PUBLISH_DY', 'ccc').strip()
PUBLISH_DY = set(SEC_IDX) if _PUB == 'all' else {x for x in _PUB.split(',') if x}
for _p, (_k, _sck, _u, _en, _fa) in SEC_IDX.items():
    if _p not in PUBLISH_DY: continue
    PARAMS[_p] = dict(kind='inst', sc=_sck, models=(ALL if _p == 'ccc' else (['ecmwf', 'gfs25'] if _sck in ('vo', 'dv', 'tadv', 'te', 'thw', 'omg') else I_CV)), unit=_u, en=_en, fa=_fa, secidx=_k)   # r82: ترازهای متعدد فقط ECMWF و GFS(0.25°)؛ (فضای هاست)
# ---- نقشه‌های ثانویه (secondary.py): همرفت، شدت، تگرگ، آذرخش، سیل‌خیزی و هشدارها؛ پنجرهٔ ۶ ساعته / ۲۴ ساعته / تجمعی
for _h, (_fa, _en, _sck, _mm) in secondary.PRODUCTS.items():
    for _w, _wfa, _wen in secondary.WINS:
        PARAMS[f'{_h}{_w}'] = dict(kind='sec', haz=_h, win=_w, sc=_sck, models=(I_CV if _mm == 'ecg' else ALL), unit='', en=f'{_en} — {_wen}', fa=f'{_fa} — {_wfa}')
for _p in [x[0] for x in PR_WIN] + [x[0] for x in SN_WIN] + ['refl', 'sigwx', 'rh', 'gust']:
    if _p in PARAMS and 'ecmwf9' not in PARAMS[_p]['models']: PARAMS[_p]['models'] = list(PARAMS[_p]['models']) + ['ecmwf9']
PARAMS['w500']['me'] = dict(sc='windup', unit='kt', k=1.94384 / 3.6)
PARAMS['gust']['me'] = dict(sc='gust', unit='km/h', k=1.0)
# ---- پارامترهای ویژهٔ نمایشگر (فقط کاشی‌های خاورمیانه؛ رنگ‌ها از نمونه‌نقشه‌های Tropical Tidbits و WXCharts)
PARAMS.update({
    'w10':   dict(kind='inst', sc='wind10', models=I_ECG, unit='kt', me_only=True, ln=True, en='MSLP (mb) & 10m Wind Speed (kt)', fa='فشار سطح دریا و سرعت باد ۱۰ متری (گره)'),
    'w250':  dict(kind='inst', sc='windup', models=I_EC, unit='kt', me_only=True, ln=True, en='250mb Wind Speed/Streamlines (kt) & MSLP Extrema (mb)', fa='سرعت باد و خطوط جریان ۲۵۰ هکتوپاسکال (گره)'),
    'w200':  dict(kind='inst', sc='windup', models=I_EC, unit='kt', me_only=True, ln=True, en='200mb Wind Speed/Streamlines (kt)', fa='سرعت باد و خطوط جریان ۲۰۰ هکتوپاسکال (گره)'),
    'z500a': dict(kind='inst', sc='z500a', models=I_EC, unit='dm', me_only=True, ln=True, en='500hPa Geopotential Height (dm) & Anomaly', fa='ارتفاع ژئوپتانسیل ۵۰۰ هکتوپاسکال و انومالی (دکامتر)'),
    't2mr':  dict(kind='inst', sc='temp', models=I_ECA, unit='°C', me_only=True, raw=True, en='Temperature 2m (°C), uncorrected', fa='دمای ۲ متری (بدون اصلاح ارتفاعی)'),
    'tmaxr': dict(kind='day', sc='temp', models=I_ECA, unit='°C', me_only=True, raw=True, en='Max. temperature 2m, 24h (°C), uncorrected', fa='دمای بیشینه ۲۴ ساعته (بدون اصلاح ارتفاعی)'),
    'tminr': dict(kind='day', sc='temp', models=I_ECA, unit='°C', me_only=True, raw=True, en='Min. temperature 2m, 24h (°C), uncorrected', fa='دمای کمینه ۲۴ ساعته (بدون اصلاح ارتفاعی)'),
})
for _a, _b in (('t2m', 't2mr'), ('tmax', 'tmaxr'), ('tmin', 'tminr')): PARAMS[_a]['alt'] = _b
# اصلاح ارتفاعی مخصوص هر پارامتر: نسخهٔ خام (فقط کاشی‌های خاورمیانه) + نسخهٔ اصلاح‌شده (پیش‌فرض)
for _a in [x[0] for x in PR_WIN] + [x[0] for x in SN_WIN] + ['rh']:
    if _a not in PARAMS: continue
    _b = _a + 'r'; PARAMS[_b] = dict(PARAMS[_a], me_only=True, raw=True, en=PARAMS[_a]['en'] + ', uncorrected', fa=PARAMS[_a]['fa'] + ' (بدون اصلاح ارتفاعی)')
    PARAMS[_b].pop('alt', None); PARAMS[_a]['alt'] = _b
# دسته‌بندی استاندارد برای منوهای نمایشگر (شناسه، نام فارسی، ترتیب)
CATS = [('pr', 'بارش', 1), ('sn', 'برف', 2), ('tp', 'دما', 3), ('hm', 'رطوبت و آب قابل بارش', 4), ('sf', 'فشار و باد سطحی', 5),
        ('ul', 'ارتفاع ژئوپتانسیل و رطوبت ترازهای بالا', 6), ('uw', 'باد در ترازهای بالا', 7), ('dy', 'دینامیک، جبهه و ابر همرفتی', 7.5), ('cv', 'همرفت و ناپایداری', 8), ('rd', 'بازتاب و هوای مهم', 9), ('sc', 'نقشه‌های ثانویه (همرفت، تگرگ، آذرخش، سیل، هشدار)', 10)]
_CAT = {'t2m': 'tp', 'tsoil': 'tp', 'tmax': 'tp', 'tmin': 'tp', 'tanom': 'tp', 't2mr': 'tp', 'tmaxr': 'tp', 'tminr': 'tp', 'rh': 'hm', 'rhr': 'hm', 'pw': 'hm', 'gust': 'sf', 'sfc': 'sf', 'w10': 'sf',
        'z850': 'ul', 'z700': 'ul', 'z500': 'ul', 'z500a': 'ul', 'w500': 'uw', 'w300': 'uw', 'w250': 'uw', 'w200': 'uw',
        'tt': 'cv', 'ko': 'cv', 'shw': 'cv', 'lr75': 'cv', 'lr85': 'cv', 'sh06': 'cv', 'sh85': 'cv', 'swt': 'cv', 'fzl': 'cv', 'hgz': 'cv',
        'ki': 'cv', 'cape': 'cv', 'cin': 'cv', 'si': 'cv', 'gdi': 'cv', 'li': 'cv', 'refl': 'rd', 'sigwx': 'rd',
        'mfc850': 'dy', 'dte': 'cv', 'thk': 'dy', 'ccc': 'dy'}
for _p in list(SEC_IDX):
    if _p[:2] in ('vo', 'dv', 'ta', 'te', 'th', 'tw') or _p[0] == 'w' and _p[1:].isdigit(): _CAT.setdefault(_p, 'dy')
for _P in PARAMS.values(): _P['models'] = [m for m in _P['models'] if m in MODELS]
for _i, (_p, _P) in enumerate(PARAMS.items()):
    _P['cat'] = _CAT.get(_p) or ('sc' if _P.get('kind') == 'sec' else 'sn' if _P.get('var') == 'snow' else 'pr'); _P['ord'] = _i

# ---------------------------------------------------------------- فیزیک
# ضرایب اصلاح ارتفاعی (هر پارامتر فرمول و ضریب مخصوص خود را دارد؛ منابع در PROJECT_CONTEXT §56)
T_LAPSE = 0.0055      # K/m؛ دما: گرادیان ۵٫۵ K/km مطابق IFS (ECMWF FUG 2.1.4.9) و ELR مشاهداتی ≈ ۴٫۵–۵٫۵ (Dutra و همکاران ۲۰۲۰)
TD_LAPSE = 0.0018     # K/m؛ نقطهٔ شبنم: کاهش نقطهٔ شبنم در بستهٔ بالارونده با نسبت اختلاط ثابت ≈ ۱٫۸ K/km (فیزیک پایه)
PREC_CHI = 0.27       # 1/km؛ بارش: P×(1+χΔz)/(1−χΔz) شکل غیرخطی Liston & Elder (2006)؛ χ قابل واسنجی است
PREC_CEIL = 2500.0    # m؛ سقف ارتفاع مؤثر: بارش زاگرس میانی تا ≈ ۲۵۰۰ m افزایش و بالاتر ثابت/کم می‌شود (Asia-Pac. J. Atmos. Sci. 2016، زاگرس میانی)
PREC_DZMAX = 1.5      # km؛ سقف |Δz| برای ضریب بارش
PREC_FMIN, PREC_FMAX = 0.5, 2.0   # حدود موقت ضریب (پیش از نرمال‌سازی)؛ مانع اصلاح افراطی تا واسنجی با ایستگاه
def es_hpa(tc): return 6.112 * np.exp(17.67 * tc / (tc + 243.5))
def td_from_rh(tc, rh):
    rh = np.clip(rh, 1, 100); g = np.log(rh / 100) + 17.67 * tc / (tc + 243.5); return 243.5 * g / (17.67 - g)
def mixr(tc, rh, p): e = es_hpa(tc) * np.clip(rh, 0, 100) / 100; return 0.622 * e / np.maximum(p - e, 1)

def k_index(T, R):
    td850, td700 = td_from_rh(T[850], R[850]), td_from_rh(T[700], R[700])
    return (T[850] - T[500]) + td850 - (T[700] - td700)
def soaring_index(T, R):
    return (T[850] - T[500]) - (T[700] - td_from_rh(T[700], R[700]))
def gdi(T, R, psfc):
    """Gálvez & Davison (2016)؛ تراز ۹۵۰ با ۹۲۵ هکتوپاسکال جایگزین شده (در داده‌های باز ۹۵۰ نیست)."""
    K = {p: T[p] + 273.15 for p in T}; L0, cp = 2.69e6, 1005.7
    th = lambda p: K[p] * (1000.0 / p) ** (2 / 7)
    rA, rB, rC = mixr(T[925], R[925], 925), 0.5 * (mixr(T[850], R[850], 850) + mixr(T[700], R[700], 700)), mixr(T[500], R[500], 500)
    thA, thB, thC = th(925), 0.5 * (th(850) + th(700)), th(500)
    eA = thA * np.exp(L0 * rA / (cp * K[850])); eB = thB * np.exp(L0 * rB / (cp * K[850])); eC = thC * np.exp(L0 * rC / (cp * K[850])) - 10
    ME = eC - 303.0; LE = 0.5 * (eA + eB) - 303.0
    CBI = np.where(LE > 0, 6.5e-2 * ME * LE, 0.0)
    MWI = np.where(K[500] > 263.15, -7.0 * (K[500] - 263.15), 0.0)
    SD = (K[925] - K[700]) + (eB - eA); II = np.where(SD < 0, 1.5 * SD, 0.0)
    TC = 18.0 - 9000.0 / np.maximum(psfc - 500.0, 50.0)
    return CBI + MWI + II + TC
def lifted_index(t2, rh2, ps, t500):
    """ذرهٔ سطحی: صعود خشک تا LCL (Bolton) و سپس شبه‌بی‌دررو تا ۵۰۰ هکتوپاسکال."""
    T = t2 + 273.15; Td = td_from_rh(t2, rh2) + 273.15
    Tl = 1 / (1 / np.maximum(Td - 56, 1) + np.log(T / Td) / 800) + 56
    pl = ps * (Tl / T) ** 3.5
    t = Tl.copy(); p = pl.copy(); steps = 40; dp = (p - 500.0) / steps
    for _ in range(steps):
        tc = t - 273.15; r = mixr(tc, 100, p); Lv = 2.501e6
        g = (287.04 * t + Lv * r) / (1005.7 + Lv * Lv * r * 0.622 / (287.04 * t * t)) / p
        t = t - g * dp; p = p - dp
    li = (t500 + 273.15) - t
    return np.where(ps > 520, li, np.nan)
def refl_from_rate(rate_mmh, snow_frac):
    r = np.maximum(rate_mmh, 0); Zr = 200 * r ** 1.6; Zs = 2000 * r ** 2.0
    Z = Zr * (1 - snow_frac) + Zs * snow_frac
    return np.where(r >= 0.05, 10 * np.log10(np.maximum(Z, 1e-3)), np.nan)
def snow_frac_t(t2): return np.clip((2.0 - t2) / 2.0, 0, 1)
def sig_weather(rate, sfrac, t2, rh2, cape, ptype=None, wind=None):
    out = np.full(rate.shape, np.nan)
    fog = (rh2 >= 97) & (rate < 0.1) & ((wind is None) | (wind < 3) if wind is not None else True)
    out[fog] = 0; out[fog & (t2 < 0)] = 1
    pr = rate >= 0.1
    lvl = np.where(rate < 1, 0, np.where(rate < 4, 1, 2))
    mix = pr & (sfrac > 0.2) & (sfrac < 0.8); sn = pr & (sfrac >= 0.8); rn = pr & (sfrac <= 0.2)
    if ptype is not None:
        ice = pr & np.isin(np.round(ptype), [3, 8, 12]); rn &= ~ice; sn &= ~ice; mix &= ~ice
        out[ice] = np.where(lvl[ice] == 0, 13, 14)
    out[rn] = 2 + lvl[rn]; out[mix] = np.where(lvl[mix] == 0, 8, 9); out[sn] = 10 + lvl[sn]
    if cape is not None:
        ts = (cape >= 300) & (rate >= 0.3) & ~sn
        out[ts & (cape < 1000)] = 6; out[ts & (cape >= 1000) & (rate >= 4)] = 7; out[ts & (cape >= 1000) & (rate < 4)] = 6
        near = (cape >= 500) & (rate >= 0.05) & (rate < 0.3) & np.isnan(out); out[near] = 5
    return out

# ---------------------------------------------------------------- خواندن داده
# ---------------------------------------------------------------- شبکهٔ گاوسی هشت‌وجهی O1280 (ECMWF IFS 9 km در Open-Meteo: متغیرها به شکل (1, 6599680))
OCT_N = 1280
@functools.lru_cache(maxsize=1)
def oct_rings():
    """عرض جغرافیایی حلقه‌ها (شمال→جنوب) و تعداد نقطهٔ هر حلقه؛ مجموع نقاط 6599680."""
    x, _ = np.polynomial.legendre.leggauss(2 * OCT_N)
    lat = np.degrees(np.arcsin(x))[::-1]
    i = np.arange(2 * OCT_N); n = np.where(i < OCT_N, 20 + 4 * i, 20 + 4 * (2 * OCT_N - 1 - i))
    return lat, n
def oct_regrid(read_slice, flip, lon180, lat_t, lon_t):
    """درون‌یابی خطی از شبکهٔ O1280 به شبکهٔ منظم (lat_t[J], lon_t[I]). read_slice(a, b) آرایهٔ ۱‌بعدی نقاط حلقه‌های a..b-1 (ترتیب فایل) را می‌دهد.
    flip: حلقهٔ صفر فایل جنوبی است؛ lon180: طول نقطهٔ اول هر حلقه −180 است (نه 0)."""
    lat, n = oct_rings()
    if flip: lat, n = lat[::-1], n[::-1]
    off = np.concatenate([[0], np.cumsum(n)]); order = np.argsort(lat); la = lat[order]
    pos = np.clip(np.searchsorted(la, lat_t), 1, len(la) - 1); a = order[pos - 1]; b = order[pos]
    w = np.clip((lat_t - la[pos - 1]) / (la[pos] - la[pos - 1]), 0, 1)
    r0 = int(min(a.min(), b.min())); r1 = int(max(a.max(), b.max())) + 1
    data = np.asarray(read_slice(r0, r1), np.float32); base = off[r0]
    def ring(r):
        nn = n[r][:, None]; xx = ((lon_t[None, :] + (180.0 if lon180 else 0.0)) % 360.0) / 360.0 * nn
        i0 = np.floor(xx); f = (xx - i0).astype(np.float32); i0 = i0.astype(np.int64) % nn; i1 = (i0 + 1) % nn
        o = (off[r] - base)[:, None]; return data[o + i0] * (1 - f) + data[o + i1] * f
    return ring(a) * (1 - w[:, None]) + ring(b) * w[:, None]

class S3Source:
    """یک «دامنه» (مثلاً ecmwf_ifs025) در s3://openmeteo/data_spatial — فقط زیرکادر ایران خوانده می‌شود."""
    def __init__(s, dom, fs):
        s.dom, s.fs = dom, fs
        nx, ny, la0, lo0, dx, dy = GRIDS[dom]
        s.nx, s.ny, s.la0, s.lo0, s.dx, s.dy = nx, ny, la0, lo0, dx, dy
        lon0, lon1, lat0, lat1 = BBOX
        s.i0 = max(0, int(math.floor((lon0 - lo0) / dx))); s.i1 = min(nx, int(math.ceil((lon1 - lo0) / dx)) + 1)
        s.j0 = max(0, int(math.floor((lat0 - la0) / dy))); s.j1 = min(ny, int(math.ceil((lat1 - la0) / dy)) + 1)
        s._hsurf = None
    def jget(s, path):
        try: return json.loads(s.fs.cat_file(f'openmeteo/data_spatial/{s.dom}/{path}'))
        except Exception: return None
    def runs(s):
        return [j for j in (s.jget('in-progress.json'), s.jget('latest.json')) if j and j.get('reference_time')]
    def tpath(s, run, vt):
        return (f'openmeteo/data_spatial/{s.dom}/{run:%Y/%m/%d/%H%M}Z/{vt:%Y-%m-%dT%H%M}.om')
    def exists(s, run, vt):
        try: return s.fs.exists(s.tpath(run, vt))
        except Exception: return False
    def _open(s, path):
        import fsspec, tempfile
        from omfiles import OmFileReader
        cache = os.path.join(tempfile.gettempdir(), 'omcache', s.dom)
        of = fsspec.open(f'blockcache::s3://{path}', mode='rb', s3={'anon': True, 'default_block_size': 262144},
                         blockcache={'cache_storage': cache, 'check_files': False})
        return OmFileReader(of), cache
    def _oct_grid(s, c, flip, lon180, lat_t, lon_t):
        lat, n = oct_rings()
        if flip: n = n[::-1]
        off = np.concatenate([[0], np.cumsum(n)])
        return oct_regrid(lambda a, b: np.asarray(c[0:1, int(off[a]):int(off[b])], dtype=np.float32).ravel(), flip, lon180, lat_t, lon_t)
    def _oct_tgt(s):
        return s.la0 + np.arange(s.j0, s.j1) * s.dy, s.lo0 + np.arange(s.i0, s.i1) * s.dx
    def _oct_detect(s, r, run, vt):
        """جهت حلقه‌ها (شمال/جنوب‌اول) و مبدأ طول جغرافیایی را با مقایسهٔ دمای ۲ متری با ECMWF 0.25° (همان اجرا/زمان) پیدا می‌کند."""
        c = r.get_child_by_name('temperature_2m')
        if tuple(c.shape) != (1, 6599680): s.orient = None; return
        ref = S3Source('ecmwf_ifs025', s.fs); rd = None; c2 = c; extra = None
        for tv in ([vt] + ([run] if vt != run else [])):            # جهت شبکه به گام وابسته نیست؛ اگر مرجع ۰٫۲۵° این گام هنوز منتشر نشده، گام اول اجرا را می‌سنجیم
            try:
                if tv != vt:
                    extra = s._open(s.tpath(run, tv)); c2 = extra[0].get_child_by_name('temperature_2m')
                rd = ref.read(run, tv, ['temperature_2m']).get('temperature_2m')
            except Exception:
                rd = None
            if rd is not None: break
        c = c2
        if rd is None:
            if extra is not None:
                try: extra[0].close()
                except Exception: pass
                import shutil; shutil.rmtree(extra[1], ignore_errors=True)
            log('  ⚠ ecmwf_ifs: مرجع ECMWF 0.25° برای تشخیص جهت شبکهٔ هشت‌وجهی هنوز منتشر نشده؛ بعداً دوباره تلاش می‌شود'); return
        try: s._oct_pick(c, ref, rd)
        finally:
            if extra is not None:
                try: extra[0].close()
                except Exception: pass
                import shutil; shutil.rmtree(extra[1], ignore_errors=True)
    def _oct_pick(s, c, ref, rd):
        lat_r = ref.la0 + np.arange(ref.j0, ref.j1) * ref.dy; lon_r = ref.lo0 + np.arange(ref.i0, ref.i1) * ref.dx
        res = []
        for flip in (0, 1):
            for l180 in (0, 1):
                g = s._oct_grid(c, flip, l180, lat_r, lon_r); rm = float(np.sqrt(np.nanmean((g - rd) ** 2))); res.append((rm, flip, l180))
        res.sort(); rm, flip, l180 = res[0]
        log(f'  ℹ ecmwf_ifs شبکهٔ هشت‌وجهی O1280 (6599680 نقطه): بهترین جهت flip={flip} lon180={l180} با RMSE دما {rm:.2f}°C نسبت به ECMWF 0.25° (دومین: {res[1][0]:.2f})')
        if rm < 3.0 and res[1][0] > rm * 1.5: s.orient = (flip, l180)
        else: s.orient = None; s.bad = True; log('  ⚠ ecmwf_ifs: جهت شبکه قطعی نشد؛ این دامنه کنار گذاشته می‌شود')
    def read(s, run, vt, names):
        import shutil
        out = {}
        r, cache = s._open(s.tpath(run, vt))
        try:
            for n in names:
                try: c = r.get_child_by_name(n)
                except Exception: continue
                shp = tuple(c.shape)
                if s.dom == 'ecmwf_ifs' and shp == (1, 6599680):
                    if not hasattr(s, 'orient'):
                        try: s._oct_detect(r, run, vt)
                        except Exception as e_: log(f'  ⚠ ecmwf_ifs: تشخیص جهت شبکه خطا داد ({type(e_).__name__}: {e_})')
                    if getattr(s, 'orient', None):
                        la_t, lo_t = s._oct_tgt(); out[n] = s._oct_grid(c, s.orient[0], s.orient[1], la_t, lo_t)
                    continue
                if shp != (s.ny, s.nx) and len(shp) == 2 and not getattr(s, 'bad', False) and not getattr(s, 'adapted', False) and s.dom == 'ecmwf_ifs':
                    # شبکهٔ واقعی ecmwf_ifs: منظم و جهانی فرض می‌شود (lon از -180، lat از -90 تا 90)؛ هندسه از روی ابعاد واقعی فایل بازسازی می‌شود
                    ny2, nx2 = shp
                    if ny2 < 200 or nx2 < 400: continue      # متغیر غیرشبکه‌ای (مثلاً ارتفاع/زمان) — نادیده بگیر، شبکه را از آن نساز
                    dx2, dy2 = 360.0 / nx2, 180.0 / (ny2 - 1)
                    if 0.5 < dx2 / s.dx < 2 and 0.5 < dy2 / s.dy < 2:
                        s.ny, s.nx, s.dx, s.dy, s.adapted = ny2, nx2, dx2, dy2, True
                        lon0, lon1, lat0, lat1 = BBOX
                        s.i0 = max(0, int(math.floor((lon0 - s.lo0) / dx2))); s.i1 = min(nx2, int(math.ceil((lon1 - s.lo0) / dx2)) + 1)
                        s.j0 = max(0, int(math.floor((lat0 - s.la0) / dy2))); s.j1 = min(ny2, int(math.ceil((lat1 - s.la0) / dy2)) + 1)
                        log(f'  ℹ شبکهٔ {s.dom}: ابعاد واقعی {shp} (گام {dx2:.4f}° × {dy2:.4f}°) پذیرفته شد')
                if shp != (s.ny, s.nx):
                    if not getattr(s, 'bad', False): s.bad = True; log(f'  ⚠ شبکهٔ {s.dom} با تعریف فرق دارد: فایل {shp} ولی تعریف {(s.ny, s.nx)}؛ این دامنه کنار گذاشته می‌شود (ابعاد واقعی را برای اصلاح گزارش کنید)')
                    continue
                out[n] = np.asarray(c[s.j0:s.j1, s.i0:s.i1], dtype=np.float32)
            if s.dom == 'ecmwf_ifs' and not getattr(s, 'dnote', False) and (not out or 'precipitation' not in out):
                s.dnote = True
                try:
                    nc = r.num_children; lst = []
                    for q in range(min(nc, 60)):
                        ch = r.get_child_by_index(q); lst.append(f'{getattr(ch, "name", q)}{tuple(ch.shape)}')
                    log(f'  ⚠ ecmwf_ifs: متغیرهای خواسته‌شده خوانده نشد ({sorted(names)[:8]}…)؛ متغیرهای موجود در فایل: ' + ' | '.join(lst))
                except Exception as e_: log(f'  ⚠ ecmwf_ifs: متغیرهای خواسته‌شده خوانده نشد؛ فهرست فایل ممکن نشد ({type(e_).__name__}: {e_})')
        finally:
            try: r.close()
            except Exception: pass
            shutil.rmtree(cache, ignore_errors=True)
        return out
    def hsurf(s):
        if s._hsurf is not None: return s._hsurf if s._hsurf is not False else None
        try:
            r, cache = s._open(f'openmeteo/data/{s.dom}/static/HSURF.om')
            node = r
            if not r.is_array:
                node = r.get_child_by_index(0)
            if s.dom == 'ecmwf_ifs' and tuple(node.shape) == (1, 6599680):
                if not getattr(s, 'orient', None): s._hsurf = None; return None
                la_t, lo_t = s._oct_tgt(); a = s._oct_grid(node, s.orient[0], s.orient[1], la_t, lo_t)
            else: a = np.asarray(node[s.j0:s.j1, s.i0:s.i1], dtype=np.float32)
            a[a < -100] = 0; s._hsurf = a
        except Exception as e:
            log(f'  ارتفاع مدل {s.dom} خوانده نشد ({e}); اصلاح ارتفاعی دما انجام نمی‌شود'); s._hsurf = False
        return s._hsurf if s._hsurf is not False else None

class MockSource(S3Source):
    """دادهٔ ساختگی برای آزمون محلی (بدون اینترنت)."""
    def __init__(s, dom, seed=0):
        super().__init__(dom, None); s.seed = seed
    def runs(s):
        now = datetime.now(UTC); r = datetime(now.year, now.month, now.day, tzinfo=UTC)
        step = 1 if 'gfs' in s.dom or 'icon' in s.dom or 'ukmo' in s.dom or 'bom' in s.dom else 3
        vts = [(r + timedelta(hours=h)).strftime('%Y-%m-%dT%H:%MZ') for h in range(0, 145, step)]
        return [dict(reference_time=r.strftime('%Y-%m-%dT%H:%M:%SZ'), valid_times=vts, completed=True)]
    def exists(s, run, vt): return True
    def read(s, run, vt, names):
        ny, nx = s.j1 - s.j0, s.i1 - s.i0
        lat = s.la0 + (np.arange(s.j0, s.j1)) * s.dy; lon = s.lo0 + (np.arange(s.i0, s.i1)) * s.dx
        LON, LAT = np.meshgrid(lon, lat); h = (vt - run).total_seconds() / 3600
        rnd = np.random.default_rng(abs(hash((s.dom, h))) % 2**32)
        blob = np.exp(-((LON - 50 - h / 20) ** 2 + (LAT - 33) ** 2) / 8) + 0.5 * np.exp(-((LON - 58) ** 2 + (LAT - 28 + h / 40) ** 2) / 4)
        base = 30 - 0.9 * (LAT - 25) + 5 * np.sin(h / 24 * 2 * np.pi)
        out = {}
        for n in names:
            if n in ('precipitation', 'snowfall_water_equivalent'):
                v = np.maximum(0, 6 * blob - 0.8 + rnd.normal(0, .2, blob.shape)) * (0.4 if n.startswith('snow') else 1)
            elif n.startswith('temperature_2m'): v = base + (2 if n.endswith('max') else -2 if n.endswith('min') else 0)
            elif n.startswith('soil_temperature'): v = base + 3
            elif n.startswith('surface_temperature'): v = base + 4
            elif n.startswith('soil_moisture'): v = 0.12 + 0.2 * blob
            elif n == 'cloud_cover': v = np.clip(20 + 90 * blob, 0, 100)
            elif n == 'visibility': v = np.clip(20000 - 19000 * blob, 100, 24000)
            elif n.startswith('relative_humidity'): v = np.clip(30 + 60 * blob, 1, 100)
            elif n == 'cape': v = 2500 * blob
            elif n == 'convective_inhibition': v = -200 * blob
            elif n == 'lifted_index': v = 4 - 8 * blob
            elif n == 'total_column_integrated_water_vapour': v = 5 + 40 * blob
            elif n == 'pressure_msl': v = 1012 + 8 * np.sin(LON / 3) + 4 * np.cos(LAT / 2)
            elif n.startswith('wind_gusts'): v = 5 + 20 * blob
            elif n.startswith('wind_u'): v = 10 + 30 * blob * (2 if 'hPa' in n else 1)
            elif n.startswith('wind_v'): v = -5 + 10 * np.sin(LON / 4)
            elif n.startswith('wind_speed'): v = 8 + 10 * blob
            elif n.startswith('wind_direction'): v = 270 + 0 * blob
            elif n.startswith('geopotential_height_'):
                p = int(n.split('_')[-1][:-3]); v = {850: 1500, 700: 3100, 500: 5800, 300: 9400, 925: 800}.get(p, 1000) + 60 * np.sin(LON / 5) - 20 * (LAT - 30)
            elif n.startswith('temperature_') and n.endswith('hPa'):
                p = int(n.split('_')[-1][:-3]); v = base - (1000 - p) * 0.07 - 3
            elif n == 'precipitation_type': v = np.where(base < 2, 5, 1).astype(float)
            elif n == 'showers': v = np.maximum(0, 4 * blob - 0.6)
            elif n.startswith('cloud_cover_'): v = np.clip(10 + 80 * blob, 0, 100)
            elif n.startswith('vertical_velocity'): v = 0.3 - 1.4 * blob
            else: continue
            out[n] = v.astype(np.float32)
        return out
    def hsurf(s):
        lat = s.la0 + (np.arange(s.j0, s.j1)) * s.dy; lon = s.lo0 + (np.arange(s.i0, s.i1)) * s.dx
        LON, LAT = np.meshgrid(lon, lat); return (1200 * np.exp(-((LON - 52) ** 2 + (LAT - 32) ** 2) / 20)).astype(np.float32)

# ---------------------------------------------------------------- کادرهای خروجی (هم‌هندسه با weather.us)
_SEA_LOGGED = set(); _ICON_LOGS = [0]
class Region:
    def __init__(s, key):
        s.key = key; R = REGIONS[key]; ax, bx, ay, by = R['geo']; s.geo = R['geo']; s.en = R['en']
        xs = np.arange(FX0, FX1 + 1); ys = np.arange(FY0, FY1 + 1)
        s.lon, s.lat = np.meshgrid((xs - ax) / bx, (ys - ay) / by)
        s.dem = np.load(os.path.join(ASSETS, f'dem_{key}.npz'))['dem'].astype(np.float32)
        from scipy.ndimage import distance_transform_edt
        s.taper = np.clip(distance_transform_edt(~np.isnan(s.dem)) / 25.0, 0, 1).astype(np.float32)   # اصلاح ارتفاعی کم‌کم تا مرز DEM صفر می‌شود
        ov = Image.open(os.path.join(ASSETS, f'overlay_{key}.png')).convert('RGBA')
        s.overlay = ov
        s._idx = {}
    def slope(s):
        """شیب ناهمواری (درجه) روی شبکهٔ منطقه از DEM؛ بیرون از DEM = NaN."""
        if getattr(s, '_slope', None) is None:
            z = np.asarray(s.dem, np.float64); dx = 111320.0 * np.cos(np.radians(s.lat)) / abs(s.geo[1]); dy = 111320.0 / abs(s.geo[3])
            gy, gx = np.gradient(np.where(np.isnan(z), np.nan, z)); sl = np.degrees(np.arctan(np.hypot(gx / dx, gy / dy)))
            s._slope = np.where(np.isnan(z), np.nan, sl).astype(np.float32)
        return s._slope
    def smooth_dem(s, dx):
        k = ('dem', round(dx, 4))
        if k not in s._idx:
            from scipy.ndimage import uniform_filter
            n = max(1, int(round(dx * abs(s.geo[1]))))
            v = (~np.isnan(s.dem)).astype(np.float32); z = np.nan_to_num(s.dem)
            s._idx[k] = (uniform_filter(z, n) / np.maximum(uniform_filter(v, n), 1e-3)).astype(np.float32)
        return s._idx[k]
    def idx(s, src):
        k = src.dom
        if k not in s._idx:
            fi = (s.lon - src.lo0) / src.dx - src.i0
            fj = (s.lat - src.la0) / src.dy - src.j0
            s._idx[k] = np.array([fj, fi])
        return s._idx[k]
    def interp(s, src, a, order=1):
        if a is None: return None
        c = s.idx(src); m = np.isnan(a)
        if m.any():
            out = map_coordinates(np.where(m, 0, a), c, order=order, mode='nearest', prefilter=(order > 1))
            w = map_coordinates((~m).astype(np.float32), c, order=order, mode='nearest', prefilter=(order > 1))
            out = np.where(w > 0.5, out / np.maximum(w, 1e-6), np.nan)
            return out.astype(np.float32)
        return map_coordinates(a, c, order=order, mode='nearest', prefilter=(order > 1)).astype(np.float32)

class MERegion(Region):
    """کادر «خاورمیانه» برای نمایشگر: شبکهٔ هم‌فاصلهٔ جغرافیایی (۳۲ پیکسل در درجه)؛ DEM ایران روی آن نمونه‌برداری می‌شود."""
    def __init__(s, iran, key='me'):
        eu = key == 'eu'; ext = EU_EXT if eu else ME_EXT; px = EU_PXD if eu else PXD; W_, H_ = (EUW, EUH) if eu else (MEW, MEH)
        s.key = key; s.en = 'Europe' if eu else 'Middle East'; s.iran = iran; s._idx = {}; s.px, s.W, s.H, s.ext = px, W_, H_, ext
        s.geo = (-ext[0] * px, float(px), ext[3] * px, -float(px))
        xs = np.arange(W_) + 0.5; ys = np.arange(H_) + 0.5
        s.lon, s.lat = np.meshgrid(ext[0] + xs / px, ext[3] - ys / px)
        s.lon = s.lon.astype(np.float32); s.lat = s.lat.astype(np.float32)
        if eu:                                                  # اروپا: بدون DEM/اصلاح ارتفاعی (فقط ترازهای بالا)
            s.dem = np.full(s.lon.shape, np.nan, np.float32); s.taper = np.zeros(s.lon.shape, np.float32)
        else:
            s.dem = s.from_iran(iran.dem)
            from scipy.ndimage import distance_transform_edt
            s.taper = np.clip(distance_transform_edt(~np.isnan(s.dem)) / (25.0 * PXD / 35.0), 0, 1).astype(np.float32)
    def from_iran(s, arr):
        """میدان روی کادر ایران (هندسهٔ weather.us) → شبکهٔ خاورمیانه؛ بیرون از کادر ایران NaN."""
        ax, bx, ay, by = REGIONS['iran']['geo']
        xi = ax + bx * s.lon - FX0; yi = ay + by * s.lat - FY0
        out = map_coordinates(np.asarray(arr, np.float32), np.array([yi, xi]), order=1, mode='constant', cval=np.nan, prefilter=False)
        return out.astype(np.float32)

VAL_STRIDE = 4                          # شبکهٔ مقدار: هر ۴ پیکسل کاشی = ۰٫۱۲۵° (۳۶۰×۲۴۰)
VAL_CATS = ('pr', 'sn', 'tp')           # بارش، برف، دما: مقدار دقیق با یک رقم اعشار
VAL_IDS = ('gust', 'w10', 'w200', 'w250', 'w300', 'w500')   # باد: مقدار دقیق بدون اعشار
def wants_value(pid, P): return P.get('cat') in VAL_CATS or pid in VAL_IDS
WIND_SCALE = {'w10': 0.5, 'w300': 1.0, 'w500': 1.0, 'w250': 2.0, 'w200': 2.0}
WIND_LV = {1000: 0.5, 925: 1.0, 850: 1.0, 700: 1.0, 500: 1.0, 300: 1.0}      # ترازهای اضافه فقط برای کاشی باد (r57)      # گام کوانتیزه (گره) کاشی باد هر پارامتر؛ بازهٔ ±(۱۲۷×گام)
ID_PTS, ID_CRC = None, 0        # فهرست نقاط «شناسایی مقدار» (id_points.py)؛ در main ساخته می‌شود
def id_init(host):
    """مراکز استان/شهرستان + نقاط مهم روستایی (geo.json هاست). اگر geo.json نبود فقط مراکز؛ سایت با crc ناهمخوان فقط بازهٔ طبقه را نشان می‌دهد."""
    global ID_PTS, ID_CRC
    places = []
    if host:
        try: places = id_points.fetch_places(host)
        except Exception as e: log(f'  ! geo.json خوانده نشد ({type(e).__name__}): نقاط روستایی بدون؛ شناسایی عددی فقط اگر سایت هم همین فهرست را بسازد')
    ID_PTS = id_points.build(id_points.load_seats(), places); ID_CRC = id_points.crc16(ID_PTS)
    log(f'نقاط شناسایی: {len(ID_PTS)} (crc {ID_CRC:04x})')

def render_me(R, field, sc_key, cont=None, cont_lvls=None, cont_fmt='%d', barbs=None, stream=None, lows=None, bold=None, cont_fine=False):
    """کاشی نمایشگر: فقط لایهٔ رنگیِ گسسته + خطوط (هم‌مقدار، بردار باد، خط جریان)؛ بدون قاب/عنوان/نوار رنگ (سایت می‌کشد). خروجی WebP بدون اتلاف."""
    _PX, _MW, _MH = getattr(R, 'px', PXD), getattr(R, 'W', MEW), getattr(R, 'H', MEH)      # r65: هندسهٔ کاشی از منطقه (me/eu)
    sc = styles.SC[sc_key]; cols = [styles.hex2rgb(c) for c in sc['colors']]; n = len(cols)
    k = classify(field, sc['edges'])
    pal = np.array(cols + [(255, 255, 255)], dtype=np.uint8)
    im = Image.fromarray(pal[np.where(k < 0, n, k)], 'RGB'); lay = None
    if cont is not None or barbs is not None or stream is not None or lows is not None:
      with MPL_LOCK:
        import matplotlib; matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        fig = plt.figure(figsize=(_MW / 100, _MH / 100), dpi=100); ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, _MW); ax.set_ylim(_MH, 0); ax.axis('off')
        fig.patch.set_alpha(0); ax.patch.set_alpha(0)
        X1, Y1 = np.arange(_MW) + 0.5, np.arange(_MH) + 0.5
        if stream is not None:
            U, V = stream; sub = 4
            ax.streamplot(X1[::sub], Y1[::sub], np.nan_to_num(U[::sub, ::sub]), -np.nan_to_num(V[::sub, ::sub]), density=2.6, color=(0.1, 0.1, 0.1, 0.55), linewidth=0.55, arrowsize=0.7, arrowstyle='->')
        if cont is not None:
            cf = gaussian_filter(np.nan_to_num(cont, nan=np.nanmean(cont)), _PX * 0.30)
            if cont_fine or (cont_lvls is not None and len(cont_lvls) > 1 and abs(float(cont_lvls[1]) - float(cont_lvls[0])) <= 1.0):                                   # گام ۱ دکامتر (تراز ۵۰۰): خط نازک؛ مضرب‌های ۵ ضخیم‌تر؛ برچسب همهٔ خطوط
                cs = ax.contour(X1, Y1, cf, levels=cont_lvls, colors='k', linewidths=0.45)
                ax.clabel(cs, fmt=cont_fmt, fontsize=6.5, inline=True, inline_spacing=2)
                mj = [l for l in cont_lvls if int(round(l)) % 5 == 0]
                if mj: ax.contour(X1, Y1, cf, levels=mj, colors='k', linewidths=1.0)
            else:
                cs = ax.contour(X1, Y1, cf, levels=cont_lvls, colors='k', linewidths=0.8)
                ax.clabel(cs, fmt=cont_fmt, fontsize=8, inline=True)
            if bold is not None:
                ax.contour(X1, Y1, cf, levels=[bold], colors='k', linewidths=1.8)
        if barbs is not None:
            bu, bv = barbs; st = int(_PX * 1.6)
            ax.barbs(X1[st // 2::st], Y1[st // 2::st], bu[st // 2::st, st // 2::st], -bv[st // 2::st, st // 2::st],
                     length=5.0, linewidth=0.6, color='#202020', barb_increments=dict(half=5, full=10, flag=50))
        if lows is not None:                                   # کمینه‌های فشار (L قرمز + مقدار)
            from scipy.ndimage import minimum_filter
            m = gaussian_filter(np.nan_to_num(lows, nan=np.nanmean(lows)), _PX * 0.6); mn = minimum_filter(m, size=int(_PX * 8)) == m
            ys, xs = np.nonzero(mn); marg = 20
            for y, x in zip(ys, xs):
                if marg < x < _MW - marg and marg < y < _MH - marg and m[y, x] < 1012:
                    ax.text(x, y - 5, 'L', color='#e0201c', fontsize=15, fontweight='bold', ha='center', va='center')
                    ax.text(x, y + 10, '%d' % round(m[y, x]), color='#e0201c', fontsize=8, fontweight='bold', ha='center', va='center')
        buf = io.BytesIO(); fig.savefig(buf, format='png', dpi=100, transparent=True); plt.close(fig); buf.seek(0)
        lay = Image.open(buf).convert('RGBA').resize((_MW, _MH))
    b = io.BytesIO(); im.save(b, 'WEBP', lossless=True, quality=100, method=4)
    lb = None
    if lay is not None: bb = io.BytesIO(); lay.save(bb, 'WEBP', lossless=True, quality=100, method=4); lb = bb.getvalue()
    return b.getvalue(), lb

# ---------------------------------------------------------------- رسم
FONT_DIR = os.path.join(os.path.dirname(__import__('matplotlib').__file__), 'mpl-data', 'fonts', 'ttf')
def font(sz, bold=False): return ImageFont.truetype(os.path.join(FONT_DIR, 'DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf'), sz)
F_T, F_S, F_L, F_XS = font(21, True), font(12), font(10), font(9)
LOGO = None
def logo():
    global LOGO
    if LOGO is None:
        im = Image.open(os.path.join(ASSETS, 'logo.png')).convert('RGBA'); k = 46 / im.height
        LOGO = im.resize((max(1, int(im.width * k)), 46), Image.LANCZOS)
    return LOGO
def fmt_edge(v):
    if v == int(v): return str(int(v))
    return ('%.2f' % v).rstrip('0').rstrip('.')
def edges_txt(e): return ', '.join('-inf' if v == -math.inf else '+' if v == math.inf else fmt_edge(v) for v in e)
def classify(field, edges):
    e = np.asarray(edges[1:-1], dtype=np.float64)
    k = np.digitize(field, e, right=False); k = np.where(np.isnan(field), -1, k)
    if edges[0] != -math.inf: k = np.where(field < edges[0], 0, k)
    return k.astype(np.int16)

MPL_LOCK = threading.Lock()
MARK = [(16 * k + 8, 0x3C, (16 * k + 8) ^ 0xA5) for k in range(16)]

def render(region, field, sc_key, title, valid, run, model, unit, marker, cont=None, cont_lvls=None, cont_fmt='%d', barbs=None, note=None, caption=None, icons=None, cont_fine=False):
    sc = styles.SC[sc_key]; cols = [styles.hex2rgb(c) for c in sc['colors']]; n = len(cols)
    k = classify(field, sc['edges'])
    pal = np.array(cols + [(255, 255, 255)], dtype=np.uint8)          # -1 → سفید (بدون داده / بدون پدیده)
    img = np.full((H, W, 3), 255, np.uint8)
    img[FY0:FY1 + 1, FX0:FX1 + 1] = pal[np.where(k < 0, n, k)]
    data_mask = np.zeros((H, W), bool); data_mask[FY0:FY1 + 1, FX0:FX1 + 1] = True
    im = Image.fromarray(img, 'RGB').convert('RGBA')
    # خطوط هم‌مقدار و بردار باد (matplotlib، فقط داخل کادر)
    if cont is not None or barbs is not None:
      with MPL_LOCK:
        import matplotlib; matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        fig = plt.figure(figsize=(W / 100, H / 100), dpi=100); ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, W); ax.set_ylim(H, 0); ax.axis('off')
        fig.patch.set_alpha(0); ax.patch.set_alpha(0)
        X, Y = np.meshgrid(np.arange(FX0, FX1 + 1), np.arange(FY0, FY1 + 1))
        if cont is not None:
            cg = gaussian_filter(np.nan_to_num(cont, nan=np.nanmean(cont)), 2)
            if cont_fine or (cont_lvls is not None and len(cont_lvls) > 1 and abs(float(cont_lvls[1]) - float(cont_lvls[0])) <= 1.0):
                cs = ax.contour(X, Y, cg, levels=cont_lvls, colors='k', linewidths=0.45)
                ax.clabel(cs, fmt=cont_fmt, fontsize=6, inline=True, inline_spacing=2)
                mj = [l for l in cont_lvls if int(round(l)) % 5 == 0]
                if mj: ax.contour(X, Y, cg, levels=mj, colors='k', linewidths=1.0)
            else:
                cs = ax.contour(X, Y, cg, levels=cont_lvls, colors='k', linewidths=0.9)
                ax.clabel(cs, fmt=cont_fmt, fontsize=7, inline=True)
        if barbs is not None:
            bu, bv = barbs; st = 34
            ax.barbs(X[st // 2::st, st // 2::st], Y[st // 2::st, st // 2::st], bu[st // 2::st, st // 2::st], -bv[st // 2::st, st // 2::st],
                     length=5.2, linewidth=0.7, color='#202020', barb_increments=dict(half=5, full=10, flag=50))
        buf = io.BytesIO(); fig.savefig(buf, format='png', dpi=100, transparent=True); plt.close(fig); buf.seek(0)
        layer = Image.open(buf).convert('RGBA').resize((W, H))
        clip = Image.new('L', (W, H), 0); ImageDraw.Draw(clip).rectangle([FX0, FY0, FX1, FY1], fill=255)
        la = np.array(layer); la[..., 3] = np.minimum(la[..., 3], np.array(clip)); im.alpha_composite(Image.fromarray(la))
    if icons: warn_icons.draw(im, icons)          # آیکن نوع هشدار (زیر مرز/نام‌ها)
    # مرزها و نام‌ها (لایهٔ MetStat)
    ov = np.array(region.overlay); ov[:FY0] = 0; ov[FY1 + 1:] = 0; ov[:, :FX0] = 0; ov[:, FX1 + 1:] = 0
    im.alpha_composite(Image.fromarray(ov))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, W - 1, FY1 + 1], outline=(0, 0, 0), width=2)
    # عنوان و زمان
    d.text((14, 630), title, font=F_T, fill=(0, 0, 0))
    vi = valid + timedelta(hours=3, minutes=30)
    t2 = vi.strftime('%a %Y-%m-%d, %H:%M') + ' GMT+0330'
    d.text((W - 10, 629), 'Valid for', font=F_S, fill=(0, 0, 0), anchor='ra'); d.text((W - 10, 645), t2, font=F_S, fill=(0, 0, 0), anchor='ra')
    # نوار رنگ: ردیف ۶۸۰ فقط رنگ‌های نوار (بدون خط جداکننده) — همان چیدمان weather.us
    bx0, bx1, by0, by1 = 3, 757, 671, 689
    xs = [round(bx0 + (bx1 + 1 - bx0) * j / n) for j in range(n + 1)]
    for j in range(n): d.rectangle([xs[j], by0, xs[j + 1] - 1, by1], fill=cols[j])
    d.line([bx0, by0 - 1, bx1, by0 - 1], fill=(0, 0, 0)); d.line([bx0, by1 + 1, bx1, by1 + 1], fill=(0, 0, 0))
    lastx = -99; e = sc['edges']
    for j in range(1, n):
        lab = fmt_edge(e[j]) if (sc_key != 'sigwx' and not sc.get('names')) else None
        if lab is None: continue
        w = d.textlength(lab, font=F_L)
        if xs[j] - w / 2 < lastx + 4: continue
        d.line([xs[j], by1 + 1, xs[j], by1 + 3], fill=(0, 0, 0)); d.text((xs[j], by1 + 4), lab, font=F_L, fill=(0, 0, 0), anchor='ma'); lastx = xs[j] + w / 2
    if sc_key == 'sigwx' or sc.get('names'):
        for j, nm in enumerate(styles.SIG_NAMES if sc_key == 'sigwx' else sc['names']):
            cx = (xs[j] + xs[j + 1]) / 2; d.text((cx, by1 + 4), nm, font=F_XS, fill=(0, 0, 0), anchor='ma')
    # پانویس
    d.text((14, 718), region.en, font=F_S, fill=(0, 0, 0))
    d.text((14, 736), f"{model['label']} {run:%H}z from {run:%Y-%m-%d/%H}z", font=F_S, fill=(0, 0, 0))
    lg = logo(); im.alpha_composite(lg, (W - lg.width - 8, 708))
    d.text((W - lg.width - 16, 742), f"Data: {model['prov']} · Open-Meteo.com (CC BY 4.0)", font=F_XS, fill=(60, 60, 60), anchor='ra')
    if caption: d.text((W - lg.width - 16, 714), caption, font=F_XS, fill=(0, 0, 0), anchor='ra')
    if note: d.text((W - lg.width - 16, 728), note, font=F_XS, fill=(60, 60, 60), anchor='ra')
    rgb = np.array(im.convert('RGB'))
    # نشانهٔ ماشینی (دو ردیف پایین): مشخصات نقشه برای سایت
    raw = json.dumps(marker, separators=(',', ':'), ensure_ascii=True).encode()
    raw = b'MS2' + len(raw).to_bytes(2, 'big') + raw
    nib = [v for b in raw for v in (b >> 4, b & 15)]
    assert len(nib) <= 2 * W, 'marker too long'
    for i, v in enumerate(nib):                     # ۱۶ رنگ رزرو: هر پیکسل نیم‌بایت
        rgb[H - 2 + i // W, i % W] = MARK[v]
    return png_exact(rgb, cols + MARK)

def png_exact(rgb, data_cols):
    flat = rgb.reshape(-1, 3); key = (flat[:, 0].astype(np.int32) << 16) | (flat[:, 1].astype(np.int32) << 8) | flat[:, 2]
    uk, inv = np.unique(key, return_inverse=True)
    if len(uk) <= 256:
        pal = np.stack([(uk >> 16) & 255, (uk >> 8) & 255, uk & 255], 1).astype(np.uint8)
        im = Image.fromarray(inv.reshape(rgb.shape[:2]).astype(np.uint8), 'P'); im.putpalette(pal.ravel().tolist())
    else:
        dk = {(c[0] << 16) | (c[1] << 8) | c[2] for c in data_cols} | {0xFFFFFF, 0}
        isd = np.isin(key, list(dk)); dlist = sorted(dk); nd = len(dlist)
        rest = flat[~isd]; K = 256 - nd
        q = Image.fromarray(rest.reshape(1, -1, 3), 'RGB').quantize(colors=K, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
        qp = np.array(q.getpalette()[:3 * K], dtype=np.uint8).reshape(-1, 3); qi = np.array(q).ravel()
        idx = np.empty(len(key), np.int32)
        dmap = {k: i for i, k in enumerate(dlist)}; idx[isd] = np.vectorize(dmap.get)(key[isd]); idx[~isd] = nd + qi
        pal = np.concatenate([np.array([[(k >> 16) & 255, (k >> 8) & 255, k & 255] for k in dlist], np.uint8), qp])
        im = Image.fromarray(idx.reshape(rgb.shape[:2]).astype(np.uint8), 'P'); im.putpalette(pal.ravel().tolist())
    b = io.BytesIO(); im.save(b, 'PNG', optimize=True); return b.getvalue()

# ---------------------------------------------------------------- اقلیم (برای انومالی) و تبدیل تاریخ
CLIM = None
def jalali_month_pos(d):
    """جای روز در سال هجری خورشیدی بر حسب ماه (۰ = وسط فروردین)."""
    y = d.year if (d.month, d.day) >= (3, 21) else d.year - 1
    doy = (d - datetime(y, 3, 21, tzinfo=UTC)).total_seconds() / 86400
    if doy < 186: return doy / 31 - 0.5
    return 6 + (doy - 186) / 30 - 0.5
def clim_at(region, d):
    if CLIM is None: return None
    co = CLIM[region.key + '_coef']; rs = CLIM[region.key + '_res'].astype(np.float32)
    m = jalali_month_pos(d); a = int(math.floor(m)) % 12; b = (a + 1) % 12; u = m - math.floor(m)
    def one(k):
        c = co[k]; r = np.kron(rs[k], np.ones((4, 4), np.float32))[:region.dem.shape[0], :region.dem.shape[1]]
        return c[0] + c[1] * region.dem + c[2] * region.lat + c[3] * region.lon + r
    return one(a) * (1 - u) + one(b) * u

ZCLIM = None
ZCLIM_URLS = ['https://downloads.psl.noaa.gov/Datasets/ncep.reanalysis.derived/pressure/hgt.mon.ltm.1991-2020.nc',
              'https://psl.noaa.gov/psd/thredds/fileServer/Datasets/ncep.reanalysis.derived/pressure/hgt.mon.ltm.1991-2020.nc',
              'https://downloads.psl.noaa.gov/Datasets/ncep.reanalysis.derived/pressure/hgt.mon.ltm.nc']
def load_zclim():
    """اقلیم ماهانهٔ ارتفاع ژئوپتانسیل ۵۰۰ هکتوپاسکال (NCEP/NCAR، ۱۹۹۱–۲۰۲۰) برای انومالی؛ در صورت دانلود‌نشدن، نقشهٔ انومالی ساخته نمی‌شود."""
    global ZCLIM
    if ZCLIM is not None: return ZCLIM or None
    ZCLIM = False
    try:
        import requests, tempfile
        path = os.path.join(tempfile.gettempdir(), 'hgt_ltm.nc')
        if not os.path.exists(path):
            for u in ZCLIM_URLS:
                try:
                    r = requests.get(u, timeout=180)
                    if r.ok and r.content[:3] in (b'CDF', b'\x89HD'): open(path, 'wb').write(r.content); break
                    else: log(f'  اقلیم Z500: HTTP {r.status_code} از {u}')
                except Exception as e: log(f'  اقلیم Z500: {u} → {e}')
        if os.path.exists(path):
            import netCDF4
            ds = netCDF4.Dataset(path); lev = np.array(ds['level'][:]); k = int(np.argmin(np.abs(lev - 500)))
            z = np.array(ds['hgt'][:, k]).astype(np.float32)           # (۱۲ ماه، lat، lon) ← lat نزولی در NCEP
            lat = np.array(ds['lat'][:]); lon = np.array(ds['lon'][:])
            if lat[0] > lat[-1]: lat = lat[::-1]; z = z[:, ::-1]
            ZCLIM = dict(z=z, lat=lat, lon=lon); log('اقلیم ارتفاع ۵۰۰ هکتوپاسکال بارگذاری شد')
        else: log('اقلیم ارتفاع ۵۰۰ هکتوپاسکال دانلود نشد؛ نقشهٔ انومالی ژئوپتانسیل ساخته نمی‌شود')
    except Exception as e: log(f'اقلیم ژئوپتانسیل خوانده نشد ({e})')
    return ZCLIM or None
def z500_clim_at(R, d):
    C = load_zclim()
    if C is None: return None
    m = (d.month - 1) + (d.day - 15) / 30.4; a = int(math.floor(m)) % 12; b = (a + 1) % 12; u = m - math.floor(m)
    z = C['z'][a] * (1 - u) + C['z'][b] * u
    fi = (np.where(R.lon < 0, R.lon + 360, R.lon) - C['lon'][0]) / (C['lon'][1] - C['lon'][0]); fj = (R.lat - C['lat'][0]) / (C['lat'][1] - C['lat'][0])
    return map_coordinates(z, np.array([fj, fi]), order=1, mode='nearest', prefilter=False).astype(np.float32)

# ---------------------------------------------------------------- پردازش یک اجرای یک مدل
SFC_VARS = {'precipitation', 'snowfall_water_equivalent', 'temperature_2m', 'temperature_2m_max', 'temperature_2m_min', 'relative_humidity_2m'}
class RunState:
    def __init__(s, model, run, srcs):
        s.model, s.run, s.srcs = model, run, srcs
        s.cum = {d: {'precip': None, 'snow': None} for d in srcs}
        s.hist = {d: {} for d in srcs}          # zamān → (cum_p, cum_s)
        s.tser = {d: {} for d in srcs}          # zamān → (t2, tmax, tmin) برای مدل‌های دمای روزانه
        s.done_i = -1; s.prev_vt = None; s.wait_hi = {}

SEC_SFC = {'showers', 'cloud_cover_low', 'cloud_cover_mid', 'wind_speed_10m', 'wind_gusts_10m', 'temperature_2m', 'relative_humidity_2m', 'wind_u_component_10m', 'wind_v_component_10m', 'cloud_cover', 'visibility', 'precipitation_type',
           'soil_moisture_0_to_7cm', 'soil_moisture_0_to_10cm', 'pressure_msl', 'cape', 'convective_inhibition', 'lifted_index', 'total_column_integrated_water_vapour', 'surface_temperature'}
SEC_UPPER = {f'{q}_{p}hPa' for q in ('temperature', 'relative_humidity', 'geopotential_height') for p in (925, 850, 700, 500, 300)} | \
            {f'wind_{c}_component_{p}hPa' for c in ('u', 'v') for p in (850, 700, 500, 300)} | {f'wind_{c}_{p}hPa' for c in ('speed', 'direction') for p in (850, 700, 500, 300)} | {'wind_direction_10m'} | (SEC_SFC - {'cloud_cover', 'visibility', 'precipitation_type', 'surface_temperature'})
MM_ON = False       # با --mm روشن می‌شود (مالتی‌مدل)
def needed_vars(mkey, pids, kind):
    v = {'precipitation', 'snowfall_water_equivalent'}
    if mkey in ('ecmwf', 'ukmo') or MM_ON: v |= {'temperature_2m'}
    if MM_ON: v |= {'wind_direction_10m', 'wind_speed_10m', 'pressure_msl', 'relative_humidity_2m', 'wind_gusts_10m'}
    if mkey == 'ecmwf': v |= {'temperature_2m_max', 'temperature_2m_min'}
    if kind == 'all':
        if mkey == 'ecmwf9':
            v |= {'temperature_2m', 'relative_humidity_2m', 'wind_gusts_10m', 'wind_u_component_10m', 'wind_v_component_10m', 'cape', 'precipitation_type'}
        if mkey == 'ecmwf':
            v |= {'relative_humidity_2m', 'total_column_integrated_water_vapour', 'cape', 'pressure_msl', 'wind_gusts_10m', 'wind_u_component_10m', 'wind_v_component_10m',
                  'soil_temperature_0_to_7cm', 'precipitation_type'}
            v |= {'wind_u_component_1000hPa', 'wind_v_component_1000hPa'}
            v |= {f'vertical_velocity_{q}hPa' for q in (850, 700, 500, 300)}          # r81/r82: امگا (اگر مدل نداشته باشد خوانده نمی‌شود)
            for p in (925, 850, 700, 500, 300, 250, 200):
                v |= {f'temperature_{p}hPa', f'relative_humidity_{p}hPa', f'geopotential_height_{p}hPa', f'wind_u_component_{p}hPa', f'wind_v_component_{p}hPa'}
        if mkey in ('gfs', 'gfs25'): v |= {'cape', 'lifted_index', 'convective_inhibition', 'relative_humidity_2m', 'pressure_msl', 'wind_u_component_10m', 'wind_v_component_10m'}
        if mkey in ('gfs', 'gfs25', 'icon'): v |= {f'vertical_velocity_{q}hPa' for q in (850, 700, 500, 300)}
        if mkey == 'gfs25': v |= {f'{q}_{p}hPa' for p in (250, 200) for q in ('wind_u_component', 'wind_v_component', 'geopotential_height')}   # r82: تاوایی/واگرایی ۲۵۰ و ۲۰۰
        if mkey in ('icon', 'ukmo', 'gfs25'): v |= SEC_UPPER                  # ترازهای فشاری همان مدل (برای شاخص‌های همرفت)
        v |= SEC_SFC                                           # ورودی هشدارها (اگر مدل نداشته باشد خوانده نمی‌شود)
    return v

FORCE = bool(os.environ.get('NWP_FORCE', '').strip() not in ('', '0')) or os.path.exists('FORCE_REGEN') or '--force' in sys.argv     # r58
FORCED = set()
class Uploader:
    def __init__(s, host, key, outdir):
        s.host, s.key, s.out = (host.rstrip('/') if host else None), key, outdir
        s.pool = ThreadPoolExecutor(3); s.fut = []; s.lock = threading.Lock(); s.n = 0
    def call(s, a, js=None, files=None, data=None):
        if not s.host: return {'have': [], 'ok': True}
        import requests
        u = f"{s.host}/nwp_upload.php?a={a}&key={requests.utils.quote(s.key)}"
        for k in range(8):                                  # r103: ۸ تلاش با عقب‌نشینی نمایی (هاست زیر بار ۵۰۲ می‌داد)
            try:
                r = requests.post(u, json=js, files=files, data=data, timeout=90)
                if r.status_code == 403: sys.exit('✗ کلید آپلود اشتباه است (upload_key در mx_config.json روی هاست)')
                try: return r.json()
                except Exception: raise RuntimeError(f'HTTP {r.status_code} [{a}] پاسخ: {r.text[:160]!r}')
            except SystemExit: raise
            except Exception as e:
                log(f'  … خطای ارتباط با هاست ({str(e)[:120]}); تلاش دوباره'); time.sleep(min(90, 5 * 2 ** k) + (hash((a, k, time.time())) % 7))
        return {}
    def put(s, mkey, run, fname, png, meta):
        def job():
            if s.out:
                p = os.path.join(s.out, mkey, run, fname); os.makedirs(os.path.dirname(p), exist_ok=True); open(p, 'wb').write(png)
            if s.host:
                r = s.call('put', data={'model': mkey, 'run': run, 'file': fname, 'meta': json.dumps(meta)}, files={'png': (os.path.basename(fname), png, 'image/webp' if fname.endswith('.webp') else 'image/png')})
                if not r.get('ok'): log(f'  ✗ آپلود {mkey}/{fname}: {r}'); return
            with s.lock: s.n += 1
        s.fut.append(s.pool.submit(job))
    def wait(s):
        for f in s.fut:
            try: f.result()
            except Exception as e: log(f'  ✗ {e}')
        s.fut = []

def scales_payload():
    out = {}
    keys = {v['sc'] for v in PARAMS.values()} | {(v.get('me') or {}).get('sc') for v in PARAMS.values()}
    for k in keys:
        if not k: continue
        sc = styles.SC[k]; out[k] = dict(c=sc['colors'], e=[None if (v == math.inf or v == -math.inf) else v for v in sc['edges']], lo=sc['edges'][0] == -math.inf, hi=sc['edges'][-1] == math.inf)
        if k == 'sigwx': out[k]['lab'] = styles.SIG_NAMES
        if sc.get('fa'): out[k]['lab'] = sc['fa']
    return out

def leads(vts, run): return [int(round((v - run).total_seconds() / 3600)) for v in vts]

class Engine:
    def __init__(s, a):
        s.a = a; s.state = {}; s.fs = None; s.mm = None
        s.regions = {k: Region(k) for k in a.regions if k not in ('me', 'eu')}
        if 'me' in a.regions:
            base = s.regions.get('iran') or Region('iran'); s.regions['me'] = MERegion(base)
        if 'eu' in a.regions:
            base = s.regions.get('iran') or Region('iran'); s.regions['eu'] = MERegion(base, 'eu')
        s.up = Uploader(a.host, a.key, a.out)
        if not a.mock:
            import s3fs
            s.fs = s3fs.S3FileSystem(anon=True, default_block_size=65536)
    def src(s, dom):
        return MockSource(dom) if s.a.mock else S3Source(dom, s.fs)
    def pick_dom(s, mkey):
        for d in MODELS[mkey]['dom']:
            S = s.src(d); r = S.runs()
            if r: return S, r
        return None, []
    def tick(s, mkey):
        M = MODELS[mkey]; S, runs = s.pick_dom(mkey)
        if not S: log(f'{M["name"]}: اطلاعات اجرا در دسترس نیست'); return False
        if getattr(S, 'bad', False): return False
        meta = max(runs, key=lambda j: j['reference_time'])
        run = datetime.strptime(meta['reference_time'][:16], '%Y-%m-%dT%H:%M').replace(tzinfo=UTC)
        if M.get('only_cyc') and run.hour not in M['only_cyc']:        # r68: فقط ران ۰۰ و ۱۲ (۰۶ و ۱۸ دیر می‌رسند و با ران بعدی همپوشانی پیدا می‌کنند)
            r0 = run; run = run.replace(hour=max(h for h in M['only_cyc'] if h <= run.hour), minute=0)
            offs = sorted({int(round((datetime.strptime(v[:16], '%Y-%m-%dT%H:%M').replace(tzinfo=UTC) - r0).total_seconds() / 3600)) for v in meta.get('valid_times', [])})
            hzz = M['hz'][run.strftime('%H')] if isinstance(M['hz'], dict) else M['hz']
            sh = int((r0 - run).total_seconds() // 3600); last = max(offs) if offs else 0
            offs = sorted(set(offs) | set(range(-sh, 0, 3)) | set(range(last - last % 6 + 6, hzz - sh + 1, 6)))      # ۳ ساعته پیش از ران قبلی + ۶ ساعته تا افق ران ۰۰/۱۲
            vl = [(r0 + timedelta(hours=o)).strftime('%Y-%m-%dT%H:%M') for o in offs]
            vl = [v for v in vl if S.exists(run, datetime.strptime(v, '%Y-%m-%dT%H:%M').replace(tzinfo=UTC))]
            meta = dict(meta, reference_time=run.strftime('%Y-%m-%dT%H:%M'), valid_times=vl, completed=True)
        rid = run.strftime('%Y%m%d%H')
        hz = M['hz'][run.strftime('%H')] if isinstance(M['hz'], dict) else M['hz']
        hz = min(hz, s.a.horizon or hz)
        vts = sorted({datetime.strptime(v[:16], '%Y-%m-%dT%H:%M').replace(tzinfo=UTC) for v in meta.get('valid_times', [])})
        vts = [v for v in vts if 0 <= (v - run).total_seconds() / 3600 <= hz]
        st = s.state.get(mkey)
        if not st or st.run != run:
            srcs = {'main': S}
            if M.get('hires'): srcs['hires'] = s.src(M['hires'])
            if M.get('upper'): srcs['upper'] = s.src(M['upper'])
            st = s.state[mkey] = RunState(mkey, run, srcs)
            r = s.up.call('begin', js={'model': mkey, 'run': rid, 'name': M['name'], 'label': M['label'],
                                       'info': dict(tclass='daily', res=M.get('res', ''), cyc=M.get('cyc', ''), prov=M['prov']),
                                       'cats': [dict(id=i, fa=fa, o=o) for i, fa, o in CATS], 'scales': scales_payload(),
                                       'params': {k: dict(fa=v['fa'], unit=v['unit'], cat=v['cat'], o=v['ord'], sc=(v.get('me') or {}).get('sc', v['sc']),
                                                          mu=(v.get('me') or {}).get('unit', v['unit']), alt=v.get('alt', ''), me=int(bool(v.get('me_only'))), ln=int(bool(v.get('cont') or v.get('barbs') or v.get('ln'))))
                                                  for k, v in PARAMS.items() if mkey in v['models']}})
            st.have = set(r.get('have', []))
            if FORCE and (mkey, rid) not in FORCED:                    # r58: بازسازی اجباری فقط یک‌بار برای هر (مدل، ران)؛ بدون آن نقشه‌های موجود روی هاست دوباره ساخته نمی‌شوند
                FORCED.add((mkey, rid)); log(f'  ⟳ بازسازی اجباری: {len(st.have)} نقشهٔ موجود دوباره ساخته و جایگزین می‌شود'); st.have = set()
            log(f'▶ {M["name"]} اجرای {rid}: {len(vts)} گام زمانی، {len(st.have)} نقشه از قبل روی هاست')
        made = 0; t0 = time.time()
        for i, vt in enumerate(vts):
            if i <= st.done_i: continue
            if s.a.max_steps and i >= s.a.max_steps: break
            if not S.exists(run, vt):                           # هنوز منتشر نشده؛ دور بعد
                if not hasattr(st, 'wlog'): st.wlog = set()
                if i not in st.wlog and i == st.done_i + 1: st.wlog.add(i); log(f'  ⏳ {M["name"]} {rid}: گام {vt:%Y%m%d%H} هنوز روی data_spatial نیست ({S.tpath(run, vt)[-60:]})؛ دور بعد دوباره بررسی می‌شود')
                break
            hs_ = st.srcs.get('hires')
            if hs_ is not None and (vt - run).total_seconds() <= 120 * 3600 and not hs_.exists(run, vt):
                first = st.wait_hi.setdefault(vt, time.time())
                if time.time() - first < 5400: break              # ICON-EU هنوز این گام را منتشر نکرده؛ تا ۹۰ دقیقه صبر
                log(f'  ICON-EU برای {vt:%Y%m%d%H} نرسید؛ ادامه فقط با ICON جهانی'); st.srcs.pop('hires'); st.hist.pop('hires', None)
            try:
                made += s.step(st, i, vt, vts)
            except Exception as e:
                m_ = str(e)
                if 'Not an OM file' in m_ or 'Corrupted' in m_ or 'Deflated' in m_ or 'Decoder error' in m_:
                    log(f'  ⏳ {M["name"]} {vt:%Y%m%d%H}: فایل هنوز کامل نشده؛ دور بعد دوباره تلاش می‌شود'); break
                traceback.print_exc(); log(f'  ✗ {M["name"]} {vt:%Y%m%d%H}: {e}'); break
            st.done_i = i; st.prev_vt = vt
            if s.mm: s.mm.progress(mkey, run, vt)
        s.up.wait()
        if made: s.up.call('sync', js={'model': mkey, 'run': rid})
        if made: log(f'■ {M["name"]} {rid}: +{made} نقشه ({time.time() - t0:.0f} ثانیه)')
        complete = st.done_i >= len(vts) - 1 and meta.get('completed', True)
        if complete and not getattr(st, 'ended', False):
            s.up.call('end', js={'model': mkey, 'run': rid}); st.ended = True
        return made > 0

    # ---------- یک گام زمانی
    def step(s, st, i, vt, vts):
        mkey = st.model; M = MODELS[mkey]; run = st.run; lead = int(round((vt - run).total_seconds() / 3600))
        dt_h = (vt - vts[i - 1]).total_seconds() / 3600 if i > 0 else 0
        want_all = (lead % 3 == 0 and lead <= 120) or lead % 6 == 0
        mine = [p for p, P in PARAMS.items() if mkey in P['models']]
        D = {}
        for name, src in st.srcs.items():
            vars_ = needed_vars(mkey, mine, 'all' if want_all else 'acc')
            if name == 'upper':
                if not want_all: continue
                vars_ = set(SEC_UPPER)                      # اولویت با 0.13°؛ هر چه آنجا نبود از 0.25°
            if name == 'hires':
                vars_ = {'precipitation', 'snowfall_water_equivalent', 'temperature_2m'}
                if not src.exists(run, vt): continue
            if name == 'upper':
                for rr in (run, run - timedelta(hours=6), run - timedelta(hours=12)):     # اجرای 0.25° ممکن است دیرتر از 0.13° منتشر شود → آخرین اجرای موجود
                    if not src.exists(rr, vt): continue
                    try:
                        D[name] = src.read(rr, vt, sorted(vars_))
                        if rr != run and not getattr(st, 'up_note', False): st.up_note = True; log(f'  ترازهای فشاری {src.dom}: اجرای {run:%Y%m%d%H} هنوز نیست؛ از اجرای {rr:%Y%m%d%H} استفاده می‌شود')
                    except Exception as e: log(f'  ترازهای فشاری {src.dom} {vt:%Y%m%d%H} خوانده نشد ({type(e).__name__}: {e})')
                    break
                else:
                    if not getattr(st, 'up_miss', False): st.up_miss = True; log(f'  ترازهای فشاری {src.dom} برای {vt:%Y%m%d%H} در هیچ‌کدام از سه اجرای اخیر پیدا نشد')
                continue
            D[name] = src.read(run, vt, sorted(vars_))
        # جمع‌های تجمعی روی شبکهٔ اصلی هر منبع
        for name, d in D.items():
            if name == 'upper': continue
            p = d.get('precipitation'); sn = d.get('snowfall_water_equivalent')
            if p is None: continue
            if sn is None: sn = p * snow_frac_t(d['temperature_2m']) if 'temperature_2m' in d else np.zeros_like(p)
            c = st.cum[name]
            if i == 0 or c['precip'] is None: c['precip'] = np.zeros_like(p); c['snow'] = np.zeros_like(p)
            if i > 0: c['precip'] = c['precip'] + np.nan_to_num(np.maximum(p, 0)); c['snow'] = c['snow'] + np.nan_to_num(np.maximum(sn, 0))
            st.hist[name][vt] = (c['precip'].copy(), c['snow'].copy())
            if 'temperature_2m' in d and (mkey == 'ecmwf' or MM_ON):
                st.tser[name][vt] = (d['temperature_2m'], d.get('temperature_2m_max', d['temperature_2m']), d.get('temperature_2m_min', d['temperature_2m']), dt_h)
        made = 0
        for rk, R in s.regions.items():
            for pid in mine:
                P = PARAMS[pid]
                if P['kind'] == 'sec': continue                     # نقشه‌های ثانویه پایین‌تر (sec_step) ساخته می‌شوند
                if P.get('me_only') and rk not in ('me', 'eu'): continue
                if rk == 'eu' and pid not in EU_PIDS: continue
                job = s.plan(P, st, vt, lead, dt_h, want_all)
                if not job: continue
                fname = f'{rk}/{pid}_{vt:%Y%m%d%H}.' + ('webp' if rk in ('me', 'eu') else 'png')
                if fname in st.have: continue
                try:
                    out = s.make(P, pid, st, D, R, vt, lead, dt_h)
                except Exception as e:
                    log(f'  ! {M["name"]} {pid} {vt:%Y%m%d%H}: {e}'); continue
                if out is None: continue
                field, extra = out
                if s.mm and rk in ('iran', 'fars', 'me'): s.mm.sink(mkey, rk, pid, run, vt, field, extra)
                if P.get('skip_empty') and not (np.nanmax(field) >= 0.1): continue
                if rk in ('me', 'eu'):
                    mo = P.get('me') or {}; sck = mo.get('sc', P['sc'])
                    if mo.get('k', 1.0) != 1.0: field = field * mo['k']
                    png, lines = render_me(R, field, sck, **{k: v for k, v in extra.items() if k in ('cont', 'cont_lvls', 'cont_fmt', 'barbs', 'stream', 'lows', 'bold', 'cont_fine')})
                    rid_ = f'{run:%Y%m%d%H}'; s.up.put(mkey, rid_, fname, png, dict(r=rk, m=mkey, p=pid, s=lead, v=f'{vt:%Y%m%d%H}'))
                    if lines: s.up.put(mkey, rid_, f'{rk}/{pid}L_{vt:%Y%m%d%H}.webp', lines, dict(r=rk, m=mkey, p=pid + 'L', s=lead, v=f'{vt:%Y%m%d%H}'))
                    if extra.get('hl') is not None:                       # r63: لایهٔ مراکز L/H (شفاف، قابل روشن/خاموش در سایت)
                        try:
                            hk, hf, hps = extra['hl']; cs_ = hl_centers.find_centers(hf, hk, hps, R.px if rk == 'eu' else PXD)
                            hb = hl_centers.encode_layer(cs_, R.W if rk == 'eu' else MEW, R.H if rk == 'eu' else MEH)
                            if hb: s.up.put(mkey, rid_, f'{rk}/{pid}H_{vt:%Y%m%d%H}.webp', hb, dict(r=rk, m=mkey, p=pid + 'H', s=lead, v=f'{vt:%Y%m%d%H}'))
                        except Exception as e_: log(f'  ! L/H {pid}: {type(e_).__name__}: {e_}')
                    if wants_value(pid, P) and rk == 'me':
                        try:
                            if ID_PTS: s.up.put(mkey, rid_, f'me/{pid}V_{vt:%Y%m%d%H}.webp', id_points.encode(field, ID_PTS, ID_CRC), dict(r=rk, m=mkey, p=pid + 'V', s=lead, v=f'{vt:%Y%m%d%H}'))
                        except Exception as e_: log(f'  ! کاشی مقدار {pid}: {type(e_).__name__}: {e_}')
                    if rk == 'me' and pid in WIND_SCALE and (extra.get('barbs') is not None or extra.get('stream') is not None):      # کاشی باد برای ذرات باد (گره)
                        try:
                            uu, vv = extra.get('barbs') if extra.get('barbs') is not None else extra.get('stream')
                            s.up.put(mkey, rid_, f'me/{pid}W_{vt:%Y%m%d%H}.webp', wind_tile.encode(uu, vv, WIND_SCALE[pid]), dict(r=rk, m=mkey, p=pid + 'W', s=lead, v=f'{vt:%Y%m%d%H}'))
                        except Exception as e_: log(f'  ! کاشی باد {pid}: {type(e_).__name__}: {e_}')
                    st.have.add(fname); made += 1
                    continue
                sc = styles.SC[P['sc']]
                mk = dict(v=1, p=pid, m=M['name'], r=f'{run:%Y%m%d%H}', t=f'{vt:%Y%m%d%H}', g=rk, h=P.get('h', 0) if P['kind'] == 'win' else (24 if P['kind'] == 'day' else 0),
                          s=P['sc'], u=P['unit'], n=P['fa'], e=edges_txt(sc['edges']))
                if P.get('wv'): mk['wv'] = P['wv']
                title = P['en']
                if P['kind'] == 'win' and P['h'] == 0: title += f', {lead}h'
                png = render(R, field, P['sc'], title, vt, run, M, P['unit'], mk, **{k_: v_ for k_, v_ in extra.items() if k_ != 'hl'})
                meta = dict(r=rk, m=mkey, p=pid, s=lead, v=f'{vt:%Y%m%d%H}')
                s.up.put(mkey, f'{run:%Y%m%d%H}', fname, png, meta); st.have.add(fname); made += 1
        if want_all and s.regions.get('me') is not None:                     # r57: کاشی باد ترازهای ۱۰۰۰/۹۲۵/۸۵۰/۷۰۰ هکتوپاسکال برای ذرات باد (بدون نقشهٔ رنگی)
            try: s.wind_levels(st, D, s.regions['me'], vt, lead)
            except Exception as e: log(f'  ! کاشی باد ترازها {M["name"]} {vt:%Y%m%d%H}: {type(e).__name__}: {e}')
        sec_p = [p for p in mine if PARAMS[p]['kind'] == 'sec']
        if sec_p and want_all and lead > 0:
            try: made += s.sec_step(st, D, vt, lead, dt_h, sec_p)
            except Exception as e: traceback.print_exc(); log(f'  ! نقشه‌های ثانویه {M["name"]} {vt:%Y%m%d%H}: {e}')
        return made

    def wind_levels(s, st, D, R, vt, lead):
        """فقط کاشی باد W (ذرات باد) برای ترازهای استاندارد؛ هر مدل هر ترازی را که داشته باشد. چیزی ساختگی نمی‌شود (تراز نبود ⇒ کاشی نیست)."""
        mkey = st.model; rid_ = f'{st.run:%Y%m%d%H}'
        for lv, sc in WIND_LV.items():
            if mkey == 'ecmwf' and f'w{lv}' in WIND_SCALE: continue                # ECMWF: این تراز را نقشهٔ خودش می‌سازد
            fname = f'me/w{lv}W_{vt:%Y%m%d%H}.webp'
            if fname in st.have: continue
            ku, kv = f'wind_u_component_{lv}hPa', f'wind_v_component_{lv}hPa'
            for nm in ('main', 'upper'):
                d = D.get(nm); src = st.srcs.get(nm)
                if d and src is not None and ku in d and kv in d:
                    u, v = R.interp(src, d[ku]) * 1.94384, R.interp(src, d[kv]) * 1.94384
                    s.up.put(mkey, rid_, fname, wind_tile.encode(u, v, sc), dict(r='me', m=mkey, p=f'w{lv}W', s=lead, v=f'{vt:%Y%m%d%H}')); st.have.add(fname); break

    # ---------- نقشه‌های ثانویه
    def accfield(s, st, R, vt, h, var='precip'):
        if s.acc(st, 'main', var, vt, h) is None: return None
        return s.blend(st, R, lambda nm: s.acc(st, nm, var, vt, h) if nm in st.hist else None)

    def sec_fields(s, st, D, R, vt, dt_h):
        d = D.get('main', {}); up = D.get('upper', {}); src = st.srcs['main']; us = st.srcs.get('upper')
        def G(name, k=1.0, order=1):        # اولویت با شبکهٔ اصلی (مثلاً GFS 0.13°)؛ اگر متغیر آنجا نبود، شبکهٔ دوم (0.25°)
            if name in d: a = R.interp(src, d[name], order)
            elif name in up and us is not None: a = R.interp(us, up[name], order)
            else: return None
            return a * k
        F = dict(cape=G('cape'), cin=G('convective_inhibition'), u10=G('wind_u_component_10m'), v10=G('wind_v_component_10m'), gust=G('wind_gusts_10m', 3.6),
                 li=G('lifted_index'), pw=G('total_column_integrated_water_vapour'), cloud=G('cloud_cover'), vis=G('visibility'), t2=G('temperature_2m'), rh2=G('relative_humidity_2m'),
                 soil=G('soil_moisture_0_to_7cm') if G('soil_moisture_0_to_7cm') is not None else G('soil_moisture_0_to_10cm'), tskin=G('surface_temperature', 1.0))
        def UVfb(u, v, spd, drn):            # مدل‌هایی مثل UKMO فقط سرعت و جهت دارند: u=−V·sin(θ), v=−V·cos(θ)
            if F.get(u) is None:
                a, b = G(spd), G(drn, 1.0, 0)
                if a is not None and b is not None: F[u] = -a * np.sin(np.radians(b)); F[v] = -a * np.cos(np.radians(b))
        UVfb('u10', 'v10', 'wind_speed_10m', 'wind_direction_10m')
        if F['u10'] is not None: F['ws10'] = np.hypot(F['u10'], F['v10'])
        else: F['ws10'] = G('wind_speed_10m')                                # UKMO/GEM: مؤلفه‌های باد ۱۰ متری نیست
        if F['gust'] is None and F['ws10'] is not None: F['gust'] = 1.5 * F['ws10'] * 3.6      # مدل تندباد ندارد (مثل ECMWF باز): ضریب تندباد ≈ ۱٫۵ (تقریبی)
        for p in (925, 850, 700, 500, 300, 250, 200):
            F[f't{p}'] = G(f'temperature_{p}hPa'); F[f'rh{p}'] = G(f'relative_humidity_{p}hPa'); F[f'z{p}'] = G(f'geopotential_height_{p}hPa')
            if p in (850, 700, 500, 300, 250, 200):
                F[f'u{p}'] = G(f'wind_u_component_{p}hPa'); F[f'v{p}'] = G(f'wind_v_component_{p}hPa'); UVfb(f'u{p}', f'v{p}', f'wind_speed_{p}hPa', f'wind_direction_{p}hPa')
        # ارتفاع سطح و فشار سطح
        hs = src.hsurf(); hm = R.interp(src, hs) if hs is not None else None
        dem = R.dem if R.key != 'me' else R.dem
        zs = np.where(np.isnan(dem), hm if hm is not None else 0.0, dem).astype(np.float32); F['zs'] = zs
        msl = G('pressure_msl'); F['msl'] = msl; F['ps'] = ((msl if msl is not None else 1013.25) * np.exp(-zs / 8434.0)).astype(np.float32)
        if F['t2'] is not None and 'temperature_2m' in d:                  # دمای ۲ متری با اصلاح ارتفاعی DEM (برای یخبندان/گرما)
            try: F['t2c'] = s.lapse(st, R, lambda: d['temperature_2m'])
            except Exception: pass
        for _q in (850, 700, 500, 300): F[f'w{_q}'] = G(f'vertical_velocity_{_q}hPa')       # r81/r82
        if 'showers' in d and dt_h > 0: F['cpr'] = R.interp(src, d['showers']) / dt_h      # بارش همرفتی (mm/h)
        F['lcc'], F['mcc'] = G('cloud_cover_low'), G('cloud_cover_mid')
        pt = G('precipitation_type', 1.0, 0)
        if pt is not None: F['iceprec'] = np.isin(np.round(pt), [3, 8, 12]).astype(np.float32)
        # شاخص‌های موجود در موتور (K، سورینگ، گالوز-داویسون) روی همین شبکه
        try:
            T = {p: F[f't{p}'] for p in (925, 850, 700, 500)}; Rh = {p: F[f'rh{p}'] for p in (925, 850, 700, 500)}
            if all(T[p] is not None and Rh[p] is not None for p in (850, 700, 500)):
                F['ki'] = k_index(T, Rh); F['si'] = soaring_index(T, Rh)
                if T[925] is not None and Rh[925] is not None: F['gdi'] = gdi(T, Rh, F['ps'])
        except Exception as e: log(f'  ! شاخص‌های K/SI/GDI: {e}')
        if 'precipitation' in d and dt_h > 0: F['pr'] = R.interp(src, d['precipitation']) / dt_h
        for h in (1, 3, 6, 12, 24): F[f'p{h}'] = s.accfield(st, R, vt, h)
        for h in (6, 24): F[f'sn{h}'] = s.accfield(st, R, vt, h, 'snow')
        F['slope'] = R.slope(); F['vt'] = vt
        try:                                                                 # شبکه برای واداشت دینامیکی (واگرایی/PVA): گام‌ها به متر
            F['lat'] = np.asarray(R.lat, np.float32); F['dym'] = abs(float(R.lat[1, 0] - R.lat[0, 0])) * 111000.0
            F['dxm'] = (abs(float(R.lon[0, 1] - R.lon[0, 0])) * 111000.0 * np.cos(np.radians(R.lat))).astype(np.float32)
        except Exception: pass
        try: F['dxkm'] = float(abs(R.lon[0, 1] - R.lon[0, 0])) * 111.0 * float(np.cos(np.radians(np.nanmean(R.lat))))   # اندازهٔ پیکسل (km) برای همسایگی بارش
        except Exception: pass
        try: F['sea'] = secondary.sea_mask(R.lon, R.lat, hm, R.dem)   # CAPE/CIN دریا در ۱ اردیبهشت تا ۵ آبان (secondary.in_cape_window)
        except Exception as e_: F['sea'] = None; log(f'  ! ماسک دریا ساخته نشد: {e_}')
        k_ = (st.model, R.key)
        if k_ not in _SEA_LOGGED:
            _SEA_LOGGED.add(k_)
            if F['sea'] is None: log(f'  ⚠ {st.model}/{R.key}: ماسک دریا نیست؛ وزن CAPE/CIN دریا کم نمی‌شود')
            else: log(f'  ✓ {st.model}/{R.key}: ماسک دریا {100 * F["sea"].mean():.1f}٪ یاخته‌ها · بازهٔ ۱ اردیبهشت تا ۵ آبان برای {vt:%Y-%m-%d}: {"فعال" if secondary.in_cape_window(vt) else "غیرفعال"}')
        return F

    def sec_step(s, st, D, vt, lead, dt_h, sec_p):
        made = 0
        if not hasattr(st, 'sec'): st.sec = {}
        for rk, R in s.regions.items():
            if rk == 'eu': continue                              # r65: کادر اروپا فقط ترازهای بالا
            acc = st.sec.setdefault(rk, secondary.SecAcc(st.run))
            events = acc.pre(vt)
            H = secondary.hazards(s.sec_fields(st, D, R, vt, dt_h))
            if H: acc.add(vt, H)
            events += acc.post(vt)
            for w, e, Hd in events:
                for pid in sec_p:
                    P = PARAMS[pid]
                    if P['win'] != w or P['haz'] not in Hd: continue
                    fname = f'{rk}/{pid}_{e:%Y%m%d%H}.' + ('webp' if rk == 'me' else 'png')
                    if fname in st.have: continue
                    s.emit(st, pid, P, R, rk, Hd[P['haz']], e, int(round((e - st.run).total_seconds() / 3600)), Hd=Hd if P['haz'] == 'warn' else None); made += 1
        return made

    def emit(s, st, pid, P, R, rk, field, vt, lead, Hd=None):
        mkey = st.model; M = MODELS[mkey]; run = st.run; rid = f'{run:%Y%m%d%H}'
        fname = f'{rk}/{pid}_{vt:%Y%m%d%H}.' + ('webp' if rk == 'me' else 'png')
        meta = dict(r=rk, m=mkey, p=pid, s=lead, v=f'{vt:%Y%m%d%H}')
        if rk == 'me':
            png, lines = render_me(R, field, P['sc'])
            s.up.put(mkey, rid, fname, png, meta)
        else:
            sc = styles.SC[P['sc']]
            mk = dict(v=1, p=pid, m=M['name'], r=rid, t=f'{vt:%Y%m%d%H}', g=rk, h=int(P['win']) if P['win'] != 'acc' else 0, s=P['sc'], u='', n=P['fa'], e=edges_txt(sc['edges']))
            icons = None
            if Hd is not None:
                try:
                    icons = warn_icons.pick(Hd, np.array(R.overlay), FX0, FY0)
                    if _ICON_LOGS[0] < 6:                                  # تشخیص: چند خط اول هر اجرا
                        _ICON_LOGS[0] += 1; wl_ = Hd.get('warn'); lv_ = 0 if wl_ is None else int((np.nan_to_num(wl_) >= 1).sum())
                        log(f'  آیکن هشدار {mkey}/{rk} {vt:%Y%m%d%H}: {len(icons)} آیکن · یاخته‌های هشدار={lv_} · کلیدها={len(Hd)}')
                except Exception as e_: log(f'  ! آیکن هشدار ساخته نشد: {type(e_).__name__}: {e_}')
            png = render(R, field, P['sc'], P['en'], vt, run, M, '', mk, note='Derived index from model fields (see MetStat docs)', icons=icons)
            s.up.put(mkey, rid, fname, png, meta)
        if s.mm and rk in ('iran', 'fars', 'me'):
            try: s.mm.sink(mkey, rk, pid, run, vt, field, {})                         # مالتی‌مدل: میدان رده‌ای خطر/هشدار
            except Exception as e_: log(f'  ! مالتی‌مدل sink {pid}: {e_}')
        st.have.add(fname)

    def plan(s, P, st, vt, lead, dt_h, want_all):
        if P['kind'] == 'sec': return False
        if lead == 0 and P['kind'] != 'inst': return False
        if P['kind'] == 'win':
            if lead > P['maxlead']: return False
            if P['h'] >= 48:                                  # ۴۸ و ۱۲۰ ساعته: پایان هر روز ساعت ۰۶ UTC (۰۹:۳۰ ایران)
                t0 = vt - timedelta(hours=P['h'])
                return vt.hour == 6 and lead >= P['h'] and (t0 == st.run or t0 in st.hist['main'])
            if lead % P['every']: return False
            if P['h'] == 0: return lead > 0
            if lead < P['h']: return False
            t0 = vt - timedelta(hours=P['h'])
            if P['h'] in (1, 3, 6) and dt_h > P['h'] + 1e-6: return False
            return t0 == st.run or t0 in st.hist['main']
        if P['kind'] == 'day':
            return vt.hour == 18 and lead >= 24
        return want_all

    def acc(s, st, name, var, vt, h):
        Hh = st.hist[name]
        if vt not in Hh: return None
        c1 = Hh[vt][0 if var == 'precip' else 1]
        if h == 0: return c1
        t0 = vt - timedelta(hours=h)
        if t0 == st.run: return c1
        if t0 not in Hh: return None
        return c1 - Hh[t0][0 if var == 'precip' else 1]

    def blend(s, st, R, name_field):
        """ICON: ICON-EU (۷ کیلومتر) در محدودهٔ خودش، ICON جهانی در بقیه؛ نوار ۱ درجه‌ای برای اتصال نرم مقدار (نه رنگ)."""
        g = name_field('main'); out = R.interp(st.srcs['main'], g)
        if 'hires' in st.srcs:
            h = name_field('hires')
            if h is not None:
                hi = R.interp(st.srcs['hires'], h)
                w = np.clip((R.lat - 29.6) / 1.0, 0, 1) * np.clip((62.4 - R.lon) / 1.0, 0, 1) * np.clip((R.lon + 23.4) / 1.0, 0, 1)
                out = np.where(np.isnan(hi), out, out * (1 - w) + np.nan_to_num(hi) * w)
        return out

    def lapse(s, st, R, field_native_fn, full=False):
        """اصلاح ارتفاعی دما با DEM ایران (۳۰ ثانیه): T + 5.5 K/km × (ارتفاع مدل − ارتفاع واقعی)."""
        src = st.srcs['main']; T = R.interp(src, field_native_fn())
        hs = src.hsurf()
        zm = R.interp(src, hs) if hs is not None else R.smooth_dem(src.dx)   # بدون فایل ارتفاع مدل: DEM هموارشده به اندازهٔ سلول مدل
        w = np.where(np.isnan(R.dem), 0, 1) if full else R.taper
        return T + w * T_LAPSE * (zm - np.nan_to_num(R.dem))

    def zpair(s, st, R, full=False):
        """ارتفاع مدل (zm) و ارتفاع DEM (zd) روی شبکهٔ خروجی و وزن میرایی تا مرز DEM."""
        src = st.srcs['main']; hs = src.hsurf()
        zm = R.interp(src, hs) if hs is not None else R.smooth_dem(src.dx)
        zd = np.where(np.isnan(R.dem), zm, R.dem)
        return zm, zd, (np.where(np.isnan(R.dem), 0, 1) if full else R.taper), src

    def precip_factor(s, st, R):
        """ضریب اصلاح ارتفاعی بارش/برف: F=(1+χΔz)/(1−χΔz) با ارتفاع‌های محدود‌شده به سقف؛ بر هر سلول مدل نرمال می‌شود تا مجموع بارش سلول حفظ شود."""
        k = ('pf', st.srcs['main'].dom)
        if k in R._idx: return R._idx[k]
        zm, zd, w, src = s.zpair(st, R)
        dz = np.clip((np.minimum(zd, PREC_CEIL) - np.minimum(zm, PREC_CEIL)) / 1000.0, -PREC_DZMAX, PREC_DZMAX)
        F = 1.0 + w * (np.clip((1 + PREC_CHI * dz) / (1 - PREC_CHI * dz), PREC_FMIN, PREC_FMAX) - 1.0)
        from scipy.ndimage import uniform_filter
        n = max(1, int(round(src.dx * abs(R.geo[1]))))
        F = (F / np.maximum(uniform_filter(F, n), 1e-3)).astype(np.float32)
        R._idx[k] = F; return F

    def make(s, P, pid, st, D, R, vt, lead, dt_h):
        mkey = st.model; d = D.get('main', {}); src = st.srcs['main']
        I = lambda a, order=1: R.interp(src, a, order)
        if R.key == 'me' and pid == 'tanom':                    # اقلیم ایستگاهی فقط روی کادر ایران تعریف است
            o = s.make(P, pid, st, D, R.iran, vt, lead, dt_h)
            return None if o is None else (R.from_iran(o[0]), {})
        if P['kind'] == 'win':
            f = s.blend(st, R, lambda nm: s.acc(st, nm, P['var'], vt, P['h']) if nm in st.hist else None)
            if f is None: return None
            f = np.maximum(f, 0)
            if not P.get('raw'): f = f * s.precip_factor(st, R)          # بارش/برف: ضریب ارتفاعی غیرخطی (خام: pid با پسوند r)
            return (f, dict(note='Elevation-adjusted: P×(1+χΔz)/(1−χΔz), χ=0.27/km, effective height capped at 2500 m, cell total conserved') if not P.get('raw') else {})
        if P['kind'] == 'day':
            ser = st.tser['main']; ts = sorted(t for t in ser if vt - timedelta(hours=24) < t <= vt)
            if len(ts) < 3: return None
            if pid in ('tmax', 'tmaxr'):
                f = lambda: np.nanmax(np.stack([ser[t][1] for t in ts]), 0)
            elif pid in ('tmin', 'tminr'):
                f = lambda: np.nanmin(np.stack([ser[t][2] for t in ts]), 0)
            else:
                f = lambda: np.nanmean(np.stack([ser[t][0] for t in ts]), 0)
            T = I(f()) if P.get('raw') else s.lapse(st, R, f, full=(pid == 'tanom'))
            if pid == 'tanom':
                C = clim_at(R, vt - timedelta(hours=12))
                if C is None: return None
                return (T - C, dict(note='Anomaly vs. 1991–2020 IRIMO station normals (Iran only)'))
            return (T, {})
        if P.get('secidx'):
            c = getattr(st, '_sf', None)
            if c is None or c[0] != (R.key, vt):
                F_ = s.sec_fields(st, D, R, vt, dt_h); c = st._sf = ((R.key, vt), secondary.indices(F_), F_)
            v = c[1].get(P['secidx'])
            if v is None: return None
            meta = {}
            if pid in SEC_CONT and len(c) > 2:
                fk, dv, (a, b, st_) = SEC_CONT[pid]; cf = c[2].get(fk)
                if cf is not None: meta = dict(cont=np.asarray(cf, np.float32) / dv, cont_lvls=np.arange(a, b + st_, st_))
            if pid == 'ccc' and c[1].get('ccc_approx'): meta['note'] = 'Approximate: model has no convective precipitation; CAPE/LI-masked total precipitation used'
            return (np.asarray(v, np.float32), meta)
        if pid == 't2m': return (s.lapse(st, R, lambda: d['temperature_2m']), {}) if 'temperature_2m' in d else None
        if pid == 't2mr': return (I(d['temperature_2m']), {}) if 'temperature_2m' in d else None
        if pid == 'w10':
            if 'pressure_msl' not in d or 'wind_u_component_10m' not in d: return None
            u, v = I(d['wind_u_component_10m']) * 1.94384, I(d['wind_v_component_10m']) * 1.94384; msl = I(d['pressure_msl'])
            return (np.hypot(u, v), dict(cont=msl, cont_lvls=np.arange(900, 1100, 4), barbs=(u, v), hl=('msl', msl, None)))      # r63: L/H از لایهٔ جدای {pid}H (قابل خاموش‌کردن)؛ دیگر در لایهٔ خطی نمی‌پزد
        if pid in ('w250', 'w200'):
            p = int(pid[1:]); u = d.get(f'wind_u_component_{p}hPa'); v = d.get(f'wind_v_component_{p}hPa')
            if u is None or v is None: return None
            U, V = I(u) * 1.94384, I(v) * 1.94384
            return (np.hypot(U, V), dict(stream=(U, V), lows=(I(d['pressure_msl']) if (p == 250 and 'pressure_msl' in d) else None)))
        if pid == 'z500a':
            g = d.get('geopotential_height_500hPa'); C = z500_clim_at(R, vt)
            if g is None or C is None: return None
            Z = I(g); return ((Z - C) / 10, dict(cont=Z / 10, cont_lvls=np.arange(480, 620, 1), bold=580, cont_fine=True))
        if pid == 'tsoil':
            v = d.get('soil_temperature_0_to_7cm', d.get('soil_temperature_0_to_10cm'))
            return (I(v), {}) if v is not None else None
        if pid == 'rhr': return (I(d['relative_humidity_2m']), {}) if 'relative_humidity_2m' in d else None
        if pid == 'rh':
            if 'relative_humidity_2m' not in d: return None
            if 'temperature_2m' not in d: return (I(d['relative_humidity_2m']), {})
            rh0 = I(d['relative_humidity_2m']); t0 = I(d['temperature_2m']); zm, zd, w, _ = s.zpair(st, R)
            dz = w * (zd - zm)                                              # + یعنی DEM بالاتر از ارتفاع مدل
            tc = t0 - T_LAPSE * dz; e0 = es_hpa(t0) * np.clip(rh0, 0, 100) / 100
            tm = 273.15 + 0.5 * (t0 + tc)                                   # بخار آب (فشار جزئی) مثل فشار هیپسومتریک با نسبت اختلاط ثابت تغییر می‌کند
            ec = e0 * np.exp(-9.80665 * dz / (287.05 * tm))
            return (np.clip(100.0 * ec / es_hpa(tc), 0, 100).astype(np.float32), dict(note='RH recomputed: T lapse-corrected (5.5 K/km), vapour pressure scaled hypsometrically (constant mixing ratio)'))
        if pid == 'pw': return (I(d['total_column_integrated_water_vapour']), {}) if 'total_column_integrated_water_vapour' in d else None
        if pid == 'cape': return (I(d['cape']), {}) if 'cape' in d else None
        if pid == 'cin': return (I(d['convective_inhibition']), {}) if 'convective_inhibition' in d else None
        if pid == 'gust': return (I(d['wind_gusts_10m']) * 3.6, {}) if 'wind_gusts_10m' in d else None
        if pid in ('ki', 'si', 'gdi'):
            U = D.get('upper', d); us = st.srcs.get('upper', src)
            T = {p: U.get(f'temperature_{p}hPa') for p in (925, 850, 700, 500)}; Rh = {p: U.get(f'relative_humidity_{p}hPa') for p in (925, 850, 700, 500)}
            if any(T[p] is None or Rh[p] is None for p in (850, 700, 500)): return None
            if pid == 'ki': f = k_index(T, Rh)
            elif pid == 'si': f = soaring_index(T, Rh)
            else:
                if T[925] is None: return None
                hs = us.hsurf(); ps = 1013.25 * np.exp(-(hs if hs is not None else 0) / 8434.0)
                if 'pressure_msl' in d and us is src: ps = d['pressure_msl'] * np.exp(-(hs if hs is not None else 0) / 8434.0)
                f = gdi(T, Rh, ps)
            return (R.interp(us, f), {})
        if pid == 'li':
            if 'lifted_index' in d: return (I(d['lifted_index']), {})
            if 'temperature_500hPa' not in d: return None
            hs = src.hsurf(); ps = d['pressure_msl'] * np.exp(-(hs if hs is not None else 0) / 8434.0)
            return (I(lifted_index(d['temperature_2m'], d['relative_humidity_2m'], ps, d['temperature_500hPa'])), {})
        if pid in ('refl', 'sigwx'):
            if 'precipitation' not in d or dt_h <= 0: return None
            rate = d['precipitation'] / dt_h
            sn = d.get('snowfall_water_equivalent')
            sf = np.clip(sn / np.maximum(d['precipitation'], 1e-3), 0, 1) if sn is not None else (snow_frac_t(d['temperature_2m']) if 'temperature_2m' in d else np.zeros_like(rate))
            if pid == 'refl':      # شدت بارش و کسر برف را روی شبکهٔ خروجی درون‌یابی (مکعبی) می‌کنیم و بعد dBZ حساب می‌شود؛ مرز لکه‌ها نرم و واقعی‌تر، بدون بلوک‌های ۰٫۲۵°
                rate_h = np.maximum(I(rate, 3), 0); sf_h = np.clip(I(sf, 1), 0, 1)
                return (refl_from_rate(rate_h, sf_h), dict(note='Simulated from model precipitation rate (Z = 200·R^1.6)'))
            if 'temperature_2m' not in d or 'relative_humidity_2m' not in d: return None
            ws = np.hypot(d['wind_u_component_10m'], d['wind_v_component_10m']) if 'wind_u_component_10m' in d else None
            g = lambda x, o=1: None if x is None else I(x, o)
            sw = sig_weather(np.maximum(g(rate, 3), 0), np.clip(g(sf), 0, 1), g(d['temperature_2m']), g(d['relative_humidity_2m']), g(d.get('cape')),
                             g(d.get('precipitation_type'), 0), g(ws))
            return (sw, {})
        if pid == 'sfc':
            if 'pressure_msl' not in d or 'relative_humidity_2m' not in d: return None
            if 'wind_u_component_10m' in d and 'wind_v_component_10m' in d: uu, vv = d['wind_u_component_10m'], d['wind_v_component_10m']
            elif 'wind_speed_10m' in d and 'wind_direction_10m' in d:               # GEM/UKMO/GFS28: فقط سرعت و جهت (m/s و درجه)
                uu, vv = -d['wind_speed_10m'] * np.sin(np.radians(d['wind_direction_10m'])), -d['wind_speed_10m'] * np.cos(np.radians(d['wind_direction_10m']))
            else: return None
            u, v = I(uu) * 1.94384, I(vv) * 1.94384
            msl = I(d['pressure_msl']); lv = np.arange(940, 1060, 2)
            return (I(d['relative_humidity_2m']), dict(cont=msl, cont_lvls=lv, barbs=(u, v), hl=('msl', msl, None)))
        if pid in ('z850', 'z700', 'z500'):
            p = int(pid[1:]); g = d.get(f'geopotential_height_{p}hPa'); rh = d.get(f'relative_humidity_{p}hPa')
            if g is None or rh is None: return None
            hsf = src.hsurf(); psl = I(d['pressure_msl'] * np.exp(-(hsf if hsf is not None else 0) / 8434.0)) if 'pressure_msl' in d else None      # r63: فشار سطح برای ماسکِ «تراز زیر زمین»
            if p == 500: return (I(rh), dict(cont=I(g) / 10, cont_lvls=np.arange(440, 620, 1), cont_fine=True, hl=(500, I(g) / 10, psl)))      # r58: گام ۱ دکامتر
            return (I(rh), dict(cont=I(g) / 10, cont_lvls=np.arange(0, 1200, 2 if p == 700 else 4), hl=(p, I(g) / 10, psl)))       # r58: ۷۰۰ گام ۲ دکامتر، ۸۵۰ گام ۴ دکامتر
        if pid in ('w500', 'w300'):
            p = int(pid[1:]); u = d.get(f'wind_u_component_{p}hPa'); v = d.get(f'wind_v_component_{p}hPa')
            if u is None: return None
            U, V = I(u), I(v)
            return (np.hypot(U, V) * 3.6, dict(barbs=(U * 1.94384, V * 1.94384)))
        return None

def main():
    global CLIM, MM_ON
    ap = argparse.ArgumentParser()
    ap.add_argument('--host'); ap.add_argument('--key', default=''); ap.add_argument('--out')
    ap.add_argument('--loop', action='store_true'); ap.add_argument('--max-minutes', type=int, default=0)
    ap.add_argument('--models', default=','.join(MODELS)); ap.add_argument('--regions', default='iran,fars,me,eu')
    ap.add_argument('--force', action='store_true', help='r58: نقشه‌های موجود روی هاست را هم دوباره بساز (یک‌بار برای هر ران). معادل: فایل FORCE_REGEN در ریشهٔ مخزن یا NWP_FORCE=1')
    ap.add_argument('--params', default='', help='فقط این پارامترها (با کاما)'); ap.add_argument('--mm', default='', help='پوشهٔ میدان‌های مدل‌ها؛ مالتی‌مدل MetStat را روشن می‌کند'); ap.add_argument('--mock', action='store_true'); ap.add_argument('--probe', action='store_true'); ap.add_argument('--max-steps', type=int, default=0); ap.add_argument('--horizon', type=int, default=0); ap.add_argument('--hourly-upto', type=int, default=0, help='سازگاری با workflow قدیمی (بدون اثر)')
    a = ap.parse_args(); a.regions = a.regions.split(','); t_end = time.time() + a.max_minutes * 60 if a.max_minutes else None
    if not a.host and not a.out: sys.exit('--host یا --out لازم است')
    if a.params:
        keep = set(a.params.split(','))
        for k in list(PARAMS):
            if k not in keep: PARAMS.pop(k)
    eng = Engine(a)
    if 'me' in a.regions: id_init(a.host)
    if a.mm:                                      # مالتی‌مدل MetStat: میدان هر مدل در a.mm ذخیره و ترکیب می‌شود
        import mm_maps; MM_ON = True; mm_maps.mm_extend_params(PARAMS)
        eng.mm = mm_maps.MMCombiner(sys.modules[__name__], eng, a.mm)
    # اقلیم ایستگاهی (برای انومالی) فقط از هاست و با کلید خوانده می‌شود؛ در مخزن عمومی نیست
    try:
        if a.host:
            import requests
            r = requests.post(f"{a.host.rstrip('/')}/nwp_upload.php?a=clim&key={requests.utils.quote(a.key)}", timeout=120)
            if r.ok and r.content[:2] == b'PK': CLIM = dict(np.load(io.BytesIO(r.content)))
        elif os.path.exists(os.path.join(HERE, 'clim_tmean.npz')): CLIM = dict(np.load(os.path.join(HERE, 'clim_tmean.npz')))
    except Exception as e: log(f'اقلیم خوانده نشد ({e}); نقشهٔ انومالی ساخته نمی‌شود')
    models = [m for m in a.models.split(',') if m in MODELS]
    if a.probe:                                   # آزمون سریع دسترسی به داده‌ها (برای گزارش خطا)
        for m in models:
            M = MODELS[m]; doms = M['dom'] + [d for d in (M.get('hires'), M.get('upper')) if d]
            for d in doms:
                S = eng.src(d); rs = S.runs()
                if not rs: log(f'✗ {m}/{d}: فایل latest/in-progress پیدا نشد'); continue
                j = max(rs, key=lambda q: q['reference_time']); vs = j.get('valid_times', []); var = j.get('variables', [])
                log(f'✓ {m}/{d}: اجرای {j["reference_time"]} · {len(vs)} گام · {len(var)} متغیر · کامل={j.get("completed")}')
                need = needed_vars(m, [], 'all') if d in M['dom'] else (SEC_UPPER if d == M.get('upper') else set())
                miss = sorted(v for v in need if var and v not in var)
                if miss: log(f'   متغیرهای ناموجود: {", ".join(miss)}')
                try:
                    run = datetime.strptime(j['reference_time'][:16], '%Y-%m-%dT%H:%M').replace(tzinfo=UTC)
                    r = None; t0 = time.time()
                    for k_ in (2, 1, 0):                       # گام‌های اول کامل‌ترند؛ اگر یکی ناقص بود بعدی
                        vt = datetime.strptime(vs[min(k_, len(vs) - 1)][:16], '%Y-%m-%dT%H:%M').replace(tzinfo=UTC)
                        try: r = S.read(run, vt, ['temperature_2m', 'precipitation']); break
                        except Exception as e_: log(f'   ⏳ گام {vt:%Y%m%d%H} هنوز کامل نیست ({e_})')
                    if r is None: raise RuntimeError('هیچ گامی خوانده نشد')
                    log('   ' + ', '.join(f'{k}: {v.shape} {np.nanmin(v):.1f}…{np.nanmax(v):.1f}' for k, v in r.items()) + f' ({time.time() - t0:.1f}s)')
                    hs = S.hsurf(); log(f'   ارتفاع مدل: {"موجود" if hs is not None else "نیست (DEM هموارشده به کار می‌رود)"}')
                except Exception as e: log(f'   ✗ خواندن نمونه: {e}')
        return
    def worker(m):
        while True:
            if t_end and time.time() > t_end: return
            try: busy = eng.tick(m)
            except SystemExit: raise
            except Exception as e: traceback.print_exc(); log(f'✗ {m}: {e}'); busy = False
            if not a.loop: return
            if not busy:
                for _ in range(30):                     # ۵ دقیقه انتظار (با بررسی سقف زمان)
                    if t_end and time.time() > t_end: return
                    time.sleep(10)
    stop = threading.Event()
    def mm_worker():
        while not stop.is_set():
            try: eng.mm.tick()
            except Exception as e: traceback.print_exc(); log(f'✗ مالتی‌مدل: {e}')
            stop.wait(20)
    if eng.mm: threading.Thread(target=mm_worker, daemon=True).start()
    with ThreadPoolExecutor(len(models)) as ex:
        for f in [ex.submit(worker, m) for m in models]: f.result()
    stop.set()
    if eng.mm:
        time.sleep(1); eng.mm.tick(final=True)
        eng.up.wait()
    log(f'پایان: {eng.up.n} نقشه ارسال شد')

if __name__ == '__main__':
    main()

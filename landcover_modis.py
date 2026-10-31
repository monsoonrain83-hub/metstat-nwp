#!/usr/bin/env python3
"""MODIS MCD12Q1 V061 (۵۰۰ m، سالانه) → برش ایران روی شبکهٔ طول/عرض جغرافیایی (برای ماژول سیل MetStat).

منبع : NASA LP DAAC، MCD12Q1.061 — Friedl, M., Sulla-Menashe, D. (2022) doi:10.5067/MODIS/MCD12Q1.061 (دادهٔ ناسا؛ با ارجاع آزاد).
ورود : حساب رایگان NASA Earthdata (https://urs.earthdata.nasa.gov) — متغیرهای محیطی EARTHDATA_USERNAME و EARTHDATA_PASSWORD
        (یا EARTHDATA_TOKEN) → در GitHub: Settings › Secrets and variables › Actions.
خروجی: data/static/landcover_modis_iran_<سال>.npz  (lc1 = IGBP، lc5 = PFT، uint8؛ lat نزولی) + .json (فراداده و راهنمای کلاس).
        بدون GDAL هم کار می‌کند (بازنمونه‌گیری شبکهٔ سینوسی با NumPy، «نزدیک‌ترین» تا کلاس‌ها ساخته نشوند).
خواندن HDF4: pyhdf (در صورت نصب) یا GDAL با درایور HDF4.
"""
import argparse, glob, json, os, sys, time
import numpy as np

# شبکهٔ سینوسی MODIS
R = 6371007.181
TILE = 1111950.5196666666          # ضلع هر کاشی (m)
NPIX = 2400
PS = TILE / NPIX                   # ≈ 463.313 m
X0, Y0 = -20015109.354, 10007554.677
BBOX = (43.4, 24.5, 63.9, 40.1)    # غرب، جنوب، شرق، شمال (ایران + حاشیه)
RES = 0.005                        # درجه (≈ ۵۵۰ m)

IGBP = {1: 'سوزنی‌برگ همیشه‌سبز', 2: 'پهن‌برگ همیشه‌سبز', 3: 'سوزنی‌برگ خزان‌کننده', 4: 'پهن‌برگ خزان‌کننده', 5: 'جنگل مختلط',
        6: 'بوتهٔ بسته', 7: 'بوتهٔ باز', 8: 'ساوانای چوبی', 9: 'ساوانا', 10: 'علفزار', 11: 'تالاب دائمی', 12: 'کشاورزی',
        13: 'شهری و ساخته‌شده', 14: 'موزاییک کشاورزی/پوشش طبیعی', 15: 'برف و یخ دائمی', 16: 'بایر یا کم‌پوشش', 17: 'آب'}   # LC_Type1 (IGBP)، ۲۵۵ = بدون برچسب
PFT = {0: 'آب', 1: 'سوزنی‌برگ همیشه‌سبز (درخت)', 2: 'پهن‌برگ همیشه‌سبز (درخت)', 3: 'سوزنی‌برگ خزان‌کننده (درخت)', 4: 'پهن‌برگ خزان‌کننده (درخت)',
       5: 'بوته', 6: 'علف (غیرکشت)', 7: 'کشت غلات', 8: 'کشت پهن‌برگ', 9: 'شهری و ساخته‌شده', 10: 'برف و یخ دائمی', 11: 'بایر'}   # LC_Type5 (PFT)، بازهٔ معتبر ۰ تا ۱۱
# هر دو جدول از راهنمای کاربر MCD12 C61 / فهرست GEE (کاتالوگ MODIS/061/MCD12Q1) گرفته شده‌اند.


def sin_to_tile_px(lon, lat):
    """طول/عرض (درجه) → (h, v, ردیف، ستون) در شبکهٔ سینوسی؛ آرایه‌ای."""
    lam, phi = np.radians(lon), np.radians(lat)
    x = R * lam * np.cos(phi); y = R * phi
    fx = (x - X0) / PS; fy = (Y0 - y) / PS          # شمارهٔ پیکسل سراسری (اعشاری)
    gc = np.floor(fx).astype(np.int64); gr = np.floor(fy).astype(np.int64)
    h, c = np.divmod(gc, NPIX); v, r = np.divmod(gr, NPIX)
    return h, v, r, c


def tile_px_center(h, v, r, c):
    """مرکز پیکسل (h,v,r,c) → طول/عرض (درجه)."""
    x = X0 + (h * NPIX + c + 0.5) * PS; y = Y0 - (v * NPIX + r + 0.5) * PS
    phi = y / R; lam = x / (R * np.cos(phi))
    return np.degrees(lam), np.degrees(phi)


def resample(tiles, bbox=BBOX, res=RES, fill=255):
    """tiles: {(h,v): آرایهٔ ۲۴۰۰×۲۴۰۰}. خروجی: (آرایه با lat نزولی، lon0، lat0)."""
    w, s, e, n = bbox
    lon = w + (np.arange(int(round((e - w) / res))) + 0.5) * res
    lat = n - (np.arange(int(round((n - s) / res))) + 0.5) * res
    LON, LAT = np.meshgrid(lon, lat)
    h, v, r, c = sin_to_tile_px(LON, LAT)
    out = np.full(LON.shape, fill, np.uint8)
    for (th, tv), arr in tiles.items():
        m = (h == th) & (v == tv)
        if m.any(): out[m] = arr[r[m], c[m]]
    return out, w, n


def read_sds(path, name):
    try:
        from pyhdf.SD import SD, SDC
        sd = SD(path, SDC.READ); a = sd.select(name)[:]; sd.end(); return np.asarray(a)
    except ImportError:
        pass
    from osgeo import gdal
    ds = gdal.Open('HDF4_EOS:EOS_GRID:"%s":MCD12Q1:%s' % (path, name))
    if ds is None: raise RuntimeError('GDAL نتوانست %s را بخواند؛ درایور HDF4 نصب است؟ (gdalinfo --formats | grep HDF4)' % name)
    return ds.ReadAsArray()


def tile_of(path):
    import re
    m = re.search(r'\.h(\d\d)v(\d\d)\.', os.path.basename(path)); return int(m.group(1)), int(m.group(2))


def download(year, outdir):
    import earthaccess
    have = {k: bool(os.environ.get(k, '').strip()) for k in ('EARTHDATA_TOKEN', 'EARTHDATA_USERNAME', 'EARTHDATA_PASSWORD')}
    print('متغیرهای ورود (فقط وجود، نه مقدار):', have, flush=True)
    for k in have:                                    # فاصله/خط‌جدید اضافهٔ انتهای Secret رایج‌ترین علت «Invalid credentials» است
        if os.environ.get(k): os.environ[k] = os.environ[k].strip()
    if not any(have.values()):
        sys.exit('هیچ Secret ی خوانده نشد: نام‌ها باید دقیقاً EARTHDATA_USERNAME و EARTHDATA_PASSWORD (یا EARTHDATA_TOKEN) باشند.')
    try:
        earthaccess.login(strategy='environment')
    except Exception as e:
        sys.exit('ورود Earthdata ناموفق: %s\n۱) username نه ایمیل؛ ۲) رمز را همان‌جا در urs.earthdata.nasa.gov امتحان کنید؛ ۳) راه مطمئن‌تر: Generate Token در urs.earthdata.nasa.gov و Secret با نام EARTHDATA_TOKEN.' % e)
    res = earthaccess.search_data(short_name='MCD12Q1', version='061', bounding_box=BBOX,
                                  temporal=('%d-01-01' % year, '%d-12-31' % year))
    if not res: return []
    return earthaccess.download(res, outdir)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--year', type=int, default=0, help='۰ = جدیدترین سالی که دانلود شود (از ۲۰۲۴ به عقب)')
    ap.add_argument('--out', default='data/static'); ap.add_argument('--work', default='_mcd12q1')
    ap.add_argument('--local', default='', help='پوشهٔ .hdf از قبل دانلودشده (بدون دانلود)')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True); os.makedirs(a.work, exist_ok=True)
    files, year = [], a.year
    if a.local:
        files = sorted(glob.glob(os.path.join(a.local, '*.hdf')))
    else:
        for y in ([a.year] if a.year else range(time.gmtime().tm_year, 2000, -1)):
            files = [f for f in download(y, a.work) if str(f).endswith('.hdf')]
            if files: year = y; break
    if not files: sys.exit('هیچ granule ای پیدا/دانلود نشد (ورود Earthdata یا سال را بررسی کنید).')
    tl1, tl5 = {}, {}
    for f in files:
        k = tile_of(str(f)); tl1[k] = read_sds(str(f), 'LC_Type1'); tl5[k] = read_sds(str(f), 'LC_Type5')
    lc1, lon0, lat0 = resample(tl1); lc5, _, _ = resample(tl5)
    base = os.path.join(a.out, 'landcover_modis_iran_%d' % year)
    np.savez_compressed(base + '.npz', lc1=lc1, lc5=lc5, lon0=lon0, lat0=lat0, res=RES, fill=255)
    meta = dict(product='MCD12Q1', version='061', year=year, tiles=sorted('h%02dv%02d' % k for k in tl1), bbox_wsen=BBOX, res_deg=RES,
                grid='lat نزولی؛ سطر ۰ = شمال؛ مرکز پیکسل (i,j) = (lat0-(i+.5)*res, lon0+(j+.5)*res)', fill=255,
                resample='نزدیک‌ترین پیکسل MODIS (بدون ساخت کلاس جدید)', classes_lc1_igbp=IGBP, classes_lc5_pft=PFT,
                citation='Friedl, M., Sulla-Menashe, D. (2022). MCD12Q1 MODIS/Terra+Aqua Land Cover Type Yearly L3 Global 500m SIN Grid V061. NASA LP DAAC. doi:10.5067/MODIS/MCD12Q1.061',
                shape=list(lc1.shape), share_lc1={str(k): round(float((lc1 == k).mean()), 4) for k in np.unique(lc1)})
    json.dump(meta, open(base + '.json', 'w'), ensure_ascii=False, indent=1)
    print('OK', base, lc1.shape, 'اندازه', os.path.getsize(base + '.npz') // 1024, 'KB', 'کاشی‌ها', meta['tiles'])


if __name__ == '__main__': main()

# آزمون هستهٔ CMIP6 با دادهٔ ساختگی (تابع شناخته‌شده) — python3 test_cmip6_core.py
import numpy as np, cmip6_core as C
ok = lambda n, c, i="": print(("PASS " if c else "FAIL ") + n + ("" if c else "  :: " + str(i))); F = []
def chk(n, c, i=""): ok(n, c, i); F.append(c)
# ۱) بازتولید یک میدان خطی دقیقاً (دوخطی روی تابع خطی دقیق است) روی شبکهٔ ۲٫۵° مدل با lat نزولی
lat = np.arange(50, 10 - 0.1, -2.5); lon = np.arange(30, 80 + 0.1, 2.5); LA, LO = np.meshgrid(lat, lon, indexing="ij")
f = 280 + 0.3 * LA + 0.1 * LO; data = np.stack([f + k for k in range(3)]); r = C.regrid(data, lat, lon)
LA2, LO2 = np.meshgrid(C.GRID_LAT, C.GRID_LON, indexing="ij"); exp = (280 + 0.3 * LA2 + 0.1 * LO2).ravel()
chk("regrid خطی دقیق", np.allclose(r[0], exp, atol=1e-9) and np.allclose(r[2], exp + 2, atol=1e-9), np.abs(r[0] - exp).max())
# lon به‌صورت ۰–۳۶۰ و ناحیهٔ ناکافی
try: C.regrid(data[:, :, :5], lat, lon[:5]); chk("ناحیهٔ ناکافی ⇒ خطا", False)
except ValueError: chk("ناحیهٔ ناکافی ⇒ خطا", True)
# ۲) annual: سال کامل/ناقص
yrs = np.repeat(np.arange(2015, 2020), 12); mos = np.tile(np.arange(1, 13), 5); cells = np.tile(((yrs - 2015) * 1.0 + mos / 100.0)[:, None], (1, C.NCELL)); keep = ~((yrs == 2017) & (mos == 5)); a = C.annual(cells[keep], yrs[keep], mos[keep], 2015, 2019)
chk("annual میانگین", abs(a[0, 0] - (0 + np.mean(np.arange(1, 13)) / 100)) < 1e-12 and abs(a[0, 4] - (4 + 0.065)) < 1e-12); chk("annual سال ناقص NaN", np.isnan(a[0, 2]) and not np.isnan(a[0, 1]))
# ۳) فصل‌ها
yrs = np.repeat(np.arange(2041, 2061), 12); mos = np.tile(np.arange(1, 13), 20); cells = np.tile(mos[:, None].astype(float), (1, C.NCELL)); sw = C.season_windows(cells, yrs, mos, [(2041, 2060)])
chk("DJF=(12+1+2)/3=5", np.allclose(sw[:, 0], 5.0)); chk("JJA=7", np.allclose(sw[:, 2], 7.0)); cells2 = cells.copy(); m = (np.isin(mos, (6, 7, 8))) & (yrs < 2052); cells2[m] = np.nan; sw2 = C.season_windows(cells2, yrs, mos, [(2041, 2060)]); chk("فصل با ۵۰٪ داده ⇒ NaN", np.isnan(sw2[0, 2]) and not np.isnan(sw2[0, 1]))
# ۴) واحد و بسته‌بندی
chk("K→°C", abs(C.to_units("tas", 300.15) - 27.0) < 1e-9); chk("pr→mm/day", abs(C.to_units("pr", 1e-5) - 0.864) < 1e-9)
p = C.pack(np.array([[27.123, np.nan, -12.345]]), "tas"); chk("pack/NaN", p[0, 0] == 2712 and p[0, 1] == -32768 and p[0, 2] == -1235 or p[0, 2] == -1234, p)
u = C.unb64(C.b64(p), p.shape); chk("b64 رفت‌وبرگشت", (u == p).all())
try: C.pack(np.array([400.0]), "tas"); chk("بیرون از int16 ⇒ خطا", False)
except ValueError: chk("بیرون از int16 ⇒ خطا", True)
# ۵) process_exp تاریخی و آینده
yh = np.repeat(np.arange(1950, 2015), 12); mh = np.tile(np.arange(1, 13), 65); d = (np.stack([f] * len(yh)) * 0 + 288.15 + (yh - 1950)[:, None, None] * 0.02); ann, seas = C.process_exp("tas", d, lat, lon, yh, mh, "historical")
chk("hist شکل", ann.shape == (C.NCELL, 65) and seas.shape == (C.NCELL, 4)); chk("hist مقدار", abs(ann[0, 10] - (15 + 0.2)) < 1e-9)
yf = np.repeat(np.arange(2015, 2101), 12); mf = np.tile(np.arange(1, 13), 86); d = np.stack([f * 0 + 290] * len(yf)); ann, seas = C.process_exp("tas", d, lat, lon, yf, mf, "ssp245"); chk("ssp شکل", ann.shape == (C.NCELL, 86) and seas.shape == (C.NCELL, 16))
print("ALL OK" if all(F) else "FAILED"); raise SystemExit(0 if all(F) else 1)

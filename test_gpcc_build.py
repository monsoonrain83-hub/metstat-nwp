"""آزمون با فایل‌های NetCDF3 ساختگیِ شبیه ساختار GPCC (عرض نزولی، زمان days since)"""
import os, sys, gzip, shutil, tempfile, json, numpy as np, datetime as dt
from scipy.io import netcdf_file
import gpcc_build as G
def mk(path, y0, nm, seed):
    lat = np.arange(89.875, -90, -0.25); lon = np.arange(-179.875, 180, 0.25); f = netcdf_file(path, "w")
    f.createDimension("time", nm); f.createDimension("lat", len(lat)); f.createDimension("lon", len(lon))
    t = f.createVariable("time", "d", ("time",)); t.units = "days since 1891-01-01 00:00:00"; la = f.createVariable("lat", "d", ("lat",)); lo = f.createVariable("lon", "d", ("lon",))
    p = f.createVariable("precip", "f", ("time", "lat", "lon")); p.units = "mm/month"; p._FillValue = np.float32(-99999.)
    base = dt.datetime(1891, 1, 1); t[:] = [(dt.datetime(y0 + m // 12, m % 12 + 1, 15) - base).days for m in range(nm)]; la[:] = lat; lo[:] = lon
    rng = np.random.default_rng(seed); LA, LO = np.meshgrid(lat, lon, indexing="ij"); A = np.zeros((nm, len(lat), len(lon)), "float32")
    for m in range(nm): A[m] = 50 + 40 * np.sin((m % 12) / 12 * 6.283) + (LA - 30) * 0.5 + rng.random(LA.shape) * 5
    A[:, :10, :10] = -99999.; p[:] = A; f.close()
d = tempfile.mkdtemp(); src = os.path.join(d, "src"); os.makedirs(src)
mk(os.path.join(src, "a_1891_1895.nc"), 1891, 60, 1); mk(os.path.join(src, "b_1896_1900.nc"), 1896, 59, 2)   # یک ماه حفره
with open(os.path.join(src, "a_1891_1895.nc"), "rb") as a, gzip.open(os.path.join(src, "a_1891_1895.nc.gz"), "wb") as b: shutil.copyfileobj(a, b)
os.remove(os.path.join(src, "a_1891_1895.nc"))
files = G.list_local(src); I, lat, lon, k0, nt, gaps, used, peak, dl = G.build(files, (24, 41, 43, 64), os.path.join(d, "c"), d, 1)
assert I.shape == (nt, len(lat), len(lon)), I.shape; assert lat[0] < lat[-1], "عرض باید صعودی شود"; assert abs(lat[1] - lat[0] - 0.25) < 1e-9
assert nt == 119 and len(gaps) == 0 or nt == 119, (nt, gaps)
assert k0 == 1891 * 12; v = I[0, 0, 0] / 10; la0, lo0 = lat[0], lon[0]
exp = 50 + 40 * np.sin(0) + (la0 - 30) * 0.5; assert abs(v - exp) < 5.5, (v, exp)   # نویز ≤ ۵
# بازخوانی دوم از cache باید همان را بدهد
I2 = G.build(G.list_local(src), (24, 41, 43, 64), os.path.join(d, "c"), d, 0)[0]; assert (I == I2).all()
# فضای ناکافی ← خطا
f0 = dict(files[0]); f0["size"] = 10**15
try: G.build([f0], (24, 41, 43, 64), os.path.join(d, "c2"), d, 1); raise SystemExit("باید خطا می‌داد")
except RuntimeError as e: assert "فضای موقت" in str(e)
print("OK", I.shape, f"gaps={gaps}", f"peak={peak/1e6:.1f}MB")

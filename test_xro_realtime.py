# آزمون محاسبات وضعیت اولیه با داده‌ی ساختگی (بدون CDS و بدون xarray)
import os, tempfile, types, datetime as dt, numpy as np, xro_realtime as RT
from scipy.io import netcdf_file
rng = np.random.default_rng(3); lat = np.arange(88, -90, -2.); lon = np.arange(0, 360, 2.); n = 12 * 40
mon = [f"{1985 + k // 12}-{k % 12 + 1:02d}" for k in range(n)]
true = np.convolve(rng.normal(0, 1, n + 5), np.ones(6) / 6, "valid")[:n] * 1.2           # «نینو» ساختگی
sst = 26 + 2 * np.cos(np.deg2rad(lat))[None, :, None] + 0.3 * np.cos(2 * np.pi * np.arange(n) / 12)[:, None, None] + 0 * lon[None, None, :]
nino = ((lat[:, None] >= -5) & (lat[:, None] <= 5) & (lon[None, :] >= 190) & (lon[None, :] <= 240))
sst = sst + true[:, None, None] * nino[None] + rng.normal(0, .05, sst.shape)
d = tempfile.mkdtemp(); p = os.path.join(d, "sst.nc"); ds = netcdf_file(p, "w"); ds.createDimension("time", n); ds.createDimension("lat", len(lat)); ds.createDimension("lon", len(lon))
t_ = ds.createVariable("time", "d", ("time",)); t_.units = "days since 1985-01-01"; t_[:] = [(dt.date(1985 + k // 12, k % 12 + 1, 1) - dt.date(1985, 1, 1)).days for k in range(n)]
ds.createVariable("lat", "f", ("lat",))[:] = lat; ds.createVariable("lon", "f", ("lon",))[:] = lon; ds.createVariable("sst", "f", ("time", "lat", "lon"))[:] = sst; ds.close()
m, S = RT.sst_series(p); assert m[0] == "1985-01" and len(m) == n
an = RT.anomalies(m, S["Nino34"], (1990, 2010)); r = np.corrcoef(an, true)[0, 1]; assert r > 0.98, r
# فایل آموزشی ساختگی با واحد دیگر (2.5 برابر + آفست)؛ ۲۴ ماه آخرِ ERSST در فایل نیست
class V:  # شبیه DataArray
    def __init__(s, v): s.values = np.array(v)
class DS(dict):
    pass
nf = n - 24; dsx = DS({"Nino34": V(2.5 * true[:nf] + 0.1)}); dsx.time = types.SimpleNamespace(values=np.array([f"{x}-01" for x in m[:nf]]))
a = types.SimpleNamespace(wwv=False, min_r=.85, min_init=None)
vals, init, hist, rep = RT.build_state(dsx, a, p); print(rep); assert init == m[-1], init
assert abs(vals["Nino34"] - (2.5 * true[-1] + 0.1)) < 0.35, (vals, 2.5 * true[-1])      # برگردانده شد به واحد فایل
# Z20: nc ساختگی ORAS5 (نمای منحنی‌وار)
yy, xx = np.meshgrid(np.arange(40), np.arange(60), indexing="ij"); nl = -20 + yy; nlo = 100 + xx * 3.5
z = np.full((40, 60), 120.); z[(nl >= -5) & (nl <= 5) & ((nlo % 360) >= 120) & ((nlo % 360) <= 280)] = 150.
p2 = os.path.join(d, "o.nc"); q = netcdf_file(p2, "w"); q.createDimension("t", 1); q.createDimension("y", 40); q.createDimension("x", 60)
q.createVariable("nav_lat", "f", ("y", "x"))[:] = nl; q.createVariable("nav_lon", "f", ("y", "x"))[:] = nlo; q.createVariable("so20chgt", "f", ("t", "y", "x"))[:] = z[None]; q.close()
assert abs(RT._z20_from_nc(p2) - 150) < 1e-6
assert RT._months("2024-11", "2025-02") == ["2024-11", "2024-12", "2025-01", "2025-02"]
print("ok", round(r, 3))

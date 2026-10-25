#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
xro_realtime.py — ساختن وضعیت اولیهٔ به‌روزِ XRO
  • شاخص‌های SST (Niño3.4، IOD، TNA، ATL3) از NOAA ERSSTv5 (PSL، ماهانه)
  • WWV از ORAS5 (CDS، عمق هم‌دمای ۲۰°C، میانگین ۱۲۰E–۸۰W و ۵S–۵N) — تفکیک ۰٫۲۵°، ماهانه
  • هر شاخص با رگرسیون روی هم‌پوشانی با فایل آموزشی XRO (indices_oras5.nc) به واحد/پایهٔ همان فایل برگردانده می‌شود؛
    اگر همبستگی از --min-r کمتر بود آن متغیر کنار گذاشته می‌شود (و به‌جای خطا، لاگ می‌نویسد).
⚠ تعریف جعبه‌ها (Niño3.4: 5S–5N,170W–120W؛ IOD=DMI؛ TNA 5.5–23.5N,57.5W–15W؛ ATL3 3S–3N,20W–0) و همچنین «WWV = میانگین Z20» (نه حجم) فرض شده؛
  رگرسیون و ضریب r در لاگ نشان می‌دهد این فرض‌ها چقدر به تعریف فایل XRO نزدیک است. NPMM/SPMM/SASD ساخته نمی‌شوند.
⚠ اجرا نشده روی داده‌ی واقعی (اینجا اینترنت/CDS نبود)؛ فقط محاسبات با دادهٔ ساختگی آزمون شده‌اند.
خروجی کش: wwv_z20.json  {"YYYY-MM": میانگین Z20 (m)}  — فقط ماه‌های جاافتاده دانلود می‌شوند.
"""
import os, io, json, sys, zipfile, tempfile, datetime as dt
import numpy as np

ERSST_URL = "https://downloads.psl.noaa.gov/Datasets/noaa.ersst.v5/sst.mnmean.nc"
BOX = {"Nino34": (-5, 5, 190, 240), "TNA": (5.5, 23.5, 302.5, 345), "ATL3": (-3, 3, 340, 360), "WTIO": (-10, 10, 50, 70), "SETIO": (-10, 0, 90, 110)}
WWV_BOX = (-5, 5, 120, 280)   # 120E–80W
def log(*a): print(*a, flush=True)


def _open_nc(path):
    """باز کردن NetCDF: netCDF4 (ERSST/ORAS5 در GitHub) و در نبودش scipy (فقط NetCDF3؛ برای آزمون)"""
    try:
        import netCDF4; ds = netCDF4.Dataset(path); return ds, (lambda v: np.ma.filled(v[:].astype(float), np.nan)), (lambda v: np.asarray(v[:]))
    except ImportError:
        from scipy.io import netcdf_file
        ds = netcdf_file(path, mmap=False); return ds, (lambda v: np.array(v.data, float)), (lambda v: np.array(v.data))

def _times(tv):
    """«days|hours since YYYY-M-D» → ['YYYY-MM']"""
    import re
    u = tv.units.decode() if isinstance(tv.units, bytes) else tv.units; m = re.match(r"(\w+) since (\d+)-(\d+)-(\d+)", u); unit, y, mo, d = m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4))
    f = {"days": 1, "hours": 1 / 24, "day": 1, "hour": 1 / 24}[unit]; b = dt.date(y, mo, d)
    return [(b + dt.timedelta(days=float(x) * f)).strftime("%Y-%m") for x in np.asarray(tv[:] if not hasattr(tv, "data") else tv.data)]

def boxmean(a, lat, lon, box):
    """میانگین وزنی cos(عرض) روی جعبه؛ a=(زمان,عرض,طول) با nan برای نبود"""
    la0, la1, lo0, lo1 = box; lon = np.asarray(lon) % 360; lat = np.asarray(lat)
    mk = ((lat >= la0) & (lat <= la1))[:, None] & ((lon >= lo0) & (lon <= lo1))[None, :]
    w = np.cos(np.deg2rad(lat))[:, None] * np.ones((1, len(lon))) * mk; out = []
    for k in range(a.shape[0]):
        x = a[k]; ok = np.isfinite(x) & (w > 0); ww = w * ok
        out.append(float((x * ww)[ok].sum() / ww.sum()) if ww.sum() > 0 else np.nan)
    return np.array(out)

def sst_series(path=None):
    """→ {name: (months[list of 'YYYY-MM'], values)} مقدار خام میانگین جعبه (بدون ناهنجاری)"""
    if path is None:
        import requests
        r = requests.get(ERSST_URL, timeout=300); r.raise_for_status(); path = os.path.join(tempfile.mkdtemp(), "sst.nc"); open(path, "wb").write(r.content)
    ds, F, G = _open_nc(path); mon = _times(ds.variables["time"]); sst = F(ds.variables["sst"]); sst[np.abs(sst) > 100] = np.nan
    lat, lon = G(ds.variables["lat"]), G(ds.variables["lon"]); S = {k: boxmean(sst, lat, lon, b) for k, b in BOX.items()}
    S["IOD"] = S["WTIO"] - S["SETIO"]; return mon, {k: S[k] for k in ("Nino34", "IOD", "TNA", "ATL3")}

def anomalies(mon, v, base=None):
    """ناهنجاری نسبت به میانگین ماهانه؛ base=(y0,y1) یا None=کل سری"""
    v = np.asarray(v, float); m = np.array([int(x[5:7]) for x in mon]); y = np.array([int(x[:4]) for x in mon]); out = np.full_like(v, np.nan)
    for k in range(1, 13):
        sel = m == k; ref = sel & np.isfinite(v) & ((y >= base[0]) & (y <= base[1]) if base else True)
        if ref.sum() >= 5: out[sel] = v[sel] - v[ref].mean()
    return out

def calibrate(file_mon, file_v, my_mon, my_v, min_n=36):
    """رگرسیون y_file = a + b·x_mine روی ماه‌های مشترک → (a, b, r, n)"""
    fm = dict(zip(file_mon, file_v)); xs, ys = [], []
    for t, x in zip(my_mon, my_v):
        y = fm.get(t)
        if y is not None and np.isfinite(x) and np.isfinite(y): xs.append(x); ys.append(y)
    if len(xs) < min_n: return None
    xs, ys = np.array(xs), np.array(ys); b, a = np.polyfit(xs, ys, 1); r = float(np.corrcoef(xs, ys)[0, 1]); return float(a), float(b), r, len(xs)

# ─────────────── ORAS5 Z20 از CDS ───────────────
def _z20_from_nc(path):
    ds, F, G = _open_nc(path); name = next((k for k, v in ds.variables.items() if k.lower().startswith("so20") or "20" in (getattr(v, "long_name", "") + k).lower() and v.ndim >= 3), None)
    if name is None: name = next(k for k, v in ds.variables.items() if v.ndim == 3 and k not in ("nav_lat", "nav_lon"))
    la = G(ds.variables["nav_lat"]).astype(float); lo = G(ds.variables["nav_lon"]).astype(float); a = F(ds.variables[name])[0]
    a[(a <= 0) | (a > 1500)] = np.nan; lo = lo % 360; la0, la1, lo0, lo1 = WWV_BOX; mk = (la >= la0) & (la <= la1) & (lo >= lo0) & (lo <= lo1) & np.isfinite(a)
    w = np.cos(np.deg2rad(la)) * mk
    if w.sum() == 0: raise ValueError("هیچ سلولی در جعبهٔ WWV نیست")
    return float((a * w)[mk].sum() / w.sum())

def fetch_z20(months, cache_path):
    """ماه‌های جاافتادهٔ Z20 را از CDS می‌گیرد (به‌ترتیب سال)؛ کش json؛ خروجی dict"""
    import cdsapi
    cache = json.load(open(cache_path)) if os.path.isfile(cache_path) else {}
    need = [m for m in months if m not in cache]; log(f"Z20: {len(cache)} ماه در کش، {len(need)} ماه باید گرفته شود")
    c = cdsapi.Client(); byy = {}
    for m in need: byy.setdefault(m[:4], []).append(m[5:7])
    for y, ms in sorted(byy.items()):
        for prod in ("consolidated", "operational"):
            try:
                tmp = os.path.join(tempfile.mkdtemp(), "oras5.zip")
                c.retrieve("reanalysis-oras5", {"product_type": [prod], "vertical_resolution": "single_level", "variable": ["depth_of_20_c_isotherm"], "year": [y], "month": ms, "format": "zip"}, tmp)
                z = zipfile.ZipFile(tmp); d = tempfile.mkdtemp(); z.extractall(d); got = 0
                for f in sorted(os.listdir(d)):
                    if not f.endswith(".nc"): continue
                    import re; mm = re.search(r"(20\d\d|19\d\d)(\d\d)", f)
                    if not mm: continue
                    cache[f"{mm.group(1)}-{mm.group(2)}"] = _z20_from_nc(os.path.join(d, f)); got += 1
                log(f"  ✓ {y} ({prod}): {got} ماه"); break
            except Exception as e: log(f"  ✗ {y} ({prod}): {str(e)[:140]}")
        json.dump(cache, open(cache_path, "w"))
    return cache

# ─────────────── ساخت وضعیت اولیه ───────────────
def build_state(ds, a, ersst_path=None):
    """ds: فایل آموزشی XRO. خروجی: (state_vals{var:val}, init_month 'YYYY-MM', hist{var:(mon,vals)}, report[list]) — مقادیر در واحد فایل"""
    fmon = [str(t)[:7] for t in ds.time.values]; rep = []; mine = {}
    mon, S = sst_series(ersst_path)
    for k, v in S.items(): mine[k] = (mon, v)
    if a.wwv:
        cache = fetch_z20([m for m in _months(a.z20_from, mon[-1])], a.z20_cache); zm = sorted(cache); mine["WWV"] = (zm, np.array([cache[m] for m in zm]))
    state, hist = {}, {}
    last_common = None
    for var, (mm, vv) in mine.items():
        if var not in ds: rep.append(f"{var}: در فایل XRO نیست"); continue
        yfile = [float(x) for x in ds[var].values]; base = (int(max(fmon[0][:4], mm[0][:4])), int(fmon[-1][:4]))
        an = anomalies(mm, vv, base); cal = calibrate(fmon, yfile, mm, an)
        if cal is None: rep.append(f"{var}: هم‌پوشانی کافی با فایل نیست"); continue
        A, B, R, N = cal; rep.append(f"{var}: r={R:.2f} شیب={B:.2f} (n={N})")
        if R < a.min_r: rep.append(f"  ⚠ {var} کنار گذاشته شد (r < {a.min_r})"); continue
        cv = A + B * an; hist[var] = (mm, cv); idx = [i for i, x in enumerate(cv) if np.isfinite(x)]
        t_last = mm[idx[-1]]; state[var] = (t_last, float(cv[idx[-1]]))
    if "Nino34" not in state: raise RuntimeError("Niño3.4 ساخته نشد")
    init = min(t for t, _ in state.values()); init = max(init, a.min_init or init)
    vals = {v: float(dict(zip(*hist[v]))[init]) for v in state if np.isfinite(dict(zip(*hist[v])).get(init, np.nan))}
    return vals, init, hist, rep

def _months(a, b):
    y, m = int(a[:4]), int(a[5:7]); out = []
    while f"{y}-{m:02d}" <= b: out.append(f"{y}-{m:02d}"); m += 1; y += m > 12; m = 1 if m > 12 else m
    return out

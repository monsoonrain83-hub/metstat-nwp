"""هستهٔ پردازش CMIP6 (فقط numpy/scipy؛ بدون ورودی/خروجی شبکه یا NetCDF) — قابل آزمون با دادهٔ ساختگی.
ورودی: آرایه‌های ماهانه [t, lat, lon] + سال و ماه هر گام. خروجی: شبکهٔ ۲°×۲° ایران، سری سالانه و میانگین فصلی ۲۰ساله، به‌صورت int16.
"""
import base64
import numpy as np
from scipy.interpolate import RegularGridInterpolator

GRID_LAT = np.arange(24.0, 40.0001, 2.0)      # ۹ ردیف
GRID_LON = np.arange(42.0, 64.0001, 2.0)      # ۱۲ ستون (۴۲ تا ۶۴؛ غرب ایران ≈ ۴۴٫۰)
NCELL = len(GRID_LAT) * len(GRID_LON)
HIST = (1950, 2014)
FUT = (2015, 2100)
BASE = (1995, 2014)                           # دورهٔ پایهٔ استاندارد برای تغییر (IPCC AR6 از ۱۸۵۰–۱۹۰۰ و ۱۹۹۵–۲۰۱۴ استفاده می‌کند)
WINDOWS = [(2021, 2040), (2041, 2060), (2061, 2080), (2081, 2100)]
SEASONS = {"DJF": (12, 1, 2), "MAM": (3, 4, 5), "JJA": (6, 7, 8), "SON": (9, 10, 11)}
SCALE = {"tas": 100.0, "pr": 1000.0}          # tas: °C×100 ؛ pr: mm/day×1000
MISSING = -32768

def to_units(var, a):
    """tas: K→°C ؛ pr: kg m-2 s-1 → mm/day"""
    a = np.asarray(a, dtype=np.float64)
    return a - 273.15 if var == "tas" else a * 86400.0

def regrid(field, lat, lon):
    """دوخطی از شبکهٔ مدل به شبکهٔ ۲°؛ field: [t, lat, lon] → [t, NCELL]. NaN در ورودی ⇒ NaN در خروجی."""
    lat = np.asarray(lat, float); lon = np.asarray(lon, float)
    if lon.max() > 180 and GRID_LON.max() <= 180: pass            # ایران در ۴۴–۶۴ شرقی؛ شبکهٔ ۰–۳۶۰ و −۱۸۰–۱۸۰ هر دو پوشش می‌دهند
    il = np.argsort(lat); jl = np.argsort(lon); f = np.asarray(field, float)[:, il][:, :, jl]; la = lat[il]; lo = lon[jl]
    if la.min() > GRID_LAT.min() or la.max() < GRID_LAT.max() or lo.min() > GRID_LON.min() or lo.max() < GRID_LON.max(): raise ValueError("ناحیهٔ دانلودشده شبکهٔ ایران را کامل نمی‌پوشاند")
    LA, LO = np.meshgrid(GRID_LAT, GRID_LON, indexing="ij"); pts = np.stack([LA.ravel(), LO.ravel()], 1); out = np.empty((f.shape[0], NCELL))
    for t in range(f.shape[0]): out[t] = RegularGridInterpolator((la, lo), f[t], method="linear")(pts)
    return out

def annual(cells, years, months, y0, y1):
    """میانگین سالانه؛ فقط سالی که هر ۱۲ ماهش هست. cells: [t, NCELL] → [NCELL, y1-y0+1] (NaN اگر ناقص)"""
    years = np.asarray(years); months = np.asarray(months); ny = y1 - y0 + 1; out = np.full((cells.shape[1], ny), np.nan)
    for k, y in enumerate(range(y0, y1 + 1)):
        m = years == y
        if m.sum() == 12 and len(set(months[m].tolist())) == 12: out[:, k] = cells[m].mean(0)
    return out

def season_windows(cells, years, months, windows):
    """میانگین هر فصل در هر پنجره: [NCELL, nwin*4] (ترتیب: پنجره، سپس DJF MAM JJA SON). فصل DJF: دی و بهمن و دسامبر همان بازهٔ سال‌ها (ساده‌سازی مرزی)."""
    years = np.asarray(years); months = np.asarray(months); out = np.full((cells.shape[1], len(windows) * 4), np.nan)
    for w, (a, b) in enumerate(windows):
        for s, (nm, ms) in enumerate(SEASONS.items()):
            m = (years >= a) & (years <= b) & np.isin(months, ms); need = (b - a + 1) * 3 * 0.9
            if m.sum() >= need: out[:, w * 4 + s] = cells[m].mean(0)
    return out

def pack(a, var):
    """float → int16 با مقیاس ثابت؛ NaN ⇒ −۳۲۷۶۸؛ بیرون از بازه ⇒ خطا (نه برش بی‌صدا)."""
    v = np.round(np.asarray(a, float) * SCALE[var]); bad = ~np.isfinite(v); v[bad] = 0
    if np.abs(v).max() > 32000: raise ValueError(f"{var}: مقدار خارج از بازهٔ int16")
    v = v.astype("<i2"); v[bad] = MISSING; return v

def b64(arr): return base64.b64encode(np.ascontiguousarray(arr).astype("<i2").tobytes()).decode("ascii")
def unb64(s, shape): return np.frombuffer(base64.b64decode(s), dtype="<i2").reshape(shape)

def process_exp(var, data, lat, lon, years, months, exp):
    """یک (مدل، سناریو، متغیر) → سری سالانه [NCELL, n] و (برای SSP) پنجره‌های فصلی یا (برای تاریخی) پایه."""
    cells = regrid(to_units(var, data), lat, lon)
    if exp == "historical":
        ann = annual(cells, years, months, *HIST); seas = season_windows(cells, years, months, [BASE])
    else:
        ann = annual(cells, years, months, *FUT); seas = season_windows(cells, years, months, WINDOWS)
    return ann, seas

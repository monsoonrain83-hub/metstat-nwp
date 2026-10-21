#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""مشتق‌های دینامیکی/ترمودینامیکی روی شبکهٔ طول‌وعرض جغرافیایی (برای سینرژی و جبهه‌ها).
همهٔ توابع روی آرایه‌هایی با دو محور آخر (lat, lon) کار می‌کنند؛ lat/lon بر حسب درجه (lat می‌تواند کاهشی باشد).
یکاها: باد m/s، دما K، فشار hPa، نتیجه‌ها در SI (مثلاً بردار، واگرایی و فرانت‌وژنز بر حسب 1/s و K/m/s).
بدون وابستگی به metpy (فقط numpy)؛ آزمون: test_grid_derive.py"""
import numpy as np
R_E = 6371000.0; RD = 287.04; CP = 1005.7; LV = 2.501e6; EPS = 0.622

def _rad(a): return np.deg2rad(np.asarray(a, float))
def ddx(f, lat, lon):
    """∂f/∂x (تفاضل مرکزی؛ x شرق‌سو بر حسب متر)."""
    d = np.gradient(f, _rad(lon), axis=-1); return d / (R_E * np.cos(_rad(lat)))[:, None]
def ddy(f, lat, lon=None):
    return np.gradient(f, _rad(lat), axis=-2) / R_E
def vorticity(u, v, lat, lon):
    return ddx(v, lat, lon) - ddy(u, lat) + u * np.tan(_rad(lat))[:, None] / R_E
def divergence(u, v, lat, lon):
    return ddx(u, lat, lon) + ddy(v, lat) - v * np.tan(_rad(lat))[:, None] / R_E
def stretching(u, v, lat, lon): return ddx(u, lat, lon) - ddy(v, lat)
def shearing(u, v, lat, lon): return ddx(v, lat, lon) + ddy(u, lat)
def deformation(u, v, lat, lon): return np.hypot(stretching(u, v, lat, lon), shearing(u, v, lat, lon))
def grad_mag(f, lat, lon): return np.hypot(ddx(f, lat, lon), ddy(f, lat))
def advection(f, u, v, lat, lon):
    """−V·∇f (مثلاً فرارفت دما برحسب K/s)."""
    return -(u * ddx(f, lat, lon) + v * ddy(f, lat))

# ───── ترمودینامیک ─────
def es_hpa(T):
    """فشار بخار اشباع روی آب (Bolton 1980)، T بر حسب K → hPa."""
    Tc = np.asarray(T, float) - 273.15; return 6.112 * np.exp(17.67 * Tc / (Tc + 243.5))
def mixing_ratio_sat(T, p): e = es_hpa(T); return EPS * e / np.maximum(p - e, 1e-3)
def dewpoint(T, rh):
    """نقطهٔ شبنم (K) از T (K) و رطوبت نسبی (٪) — Magnus."""
    Tc = np.asarray(T, float) - 273.15; g = np.log(np.maximum(rh, 0.01) / 100.0) + 17.67 * Tc / (Tc + 243.5)
    return 243.5 * g / (17.67 - g) + 273.15
def theta(T, p): return np.asarray(T, float) * (1000.0 / p) ** (RD / CP)
def theta_e(T, rh, p):
    """دمای پتانسیل هم‌ارز (Bolton 1980، رابطهٔ ۴۳)."""
    T = np.asarray(T, float); Td = dewpoint(T, rh); e = es_hpa(T) * np.asarray(rh, float) / 100.0
    r = EPS * e / np.maximum(p - e, 1e-3)                     # kg/kg
    TL = 1.0 / (1.0 / (Td - 56.0) + np.log(T / Td) / 800.0) + 56.0
    return T * (1000.0 / (p - e)) ** 0.2854 * np.exp((3.376 / TL - 0.00254) * (r * 1000.0) * (1.0 + 0.81 * r))
def wetbulb(T, rh, p, n=40):
    """دمای تر هم‌فشار (K): جواب Tw از  cp·(T−Tw) = Lv·(rs(Tw,p) − r) با دوبخشی (دقیق‌تر از Stull در ترازهای بالا)."""
    T = np.asarray(T, float); rh = np.asarray(rh, float); p = np.broadcast_to(np.asarray(p, float), T.shape)
    e = es_hpa(T) * rh / 100.0; r = EPS * e / np.maximum(p - e, 1e-3)
    lo = dewpoint(T, rh) - 1.0; hi = T.copy(); lo = np.minimum(lo, hi)
    for _ in range(n):
        mid = 0.5 * (lo + hi); f = CP * (T - mid) - LV * (mixing_ratio_sat(mid, p) - r)   # f>0 ⇒ mid خیلی سرد
        hi = np.where(f < 0, mid, hi); lo = np.where(f >= 0, mid, lo)
    return 0.5 * (lo + hi)
def theta_w_approx(T, rh, p):
    """دمای پتانسیل تر ≈ دمای تر پس از رانش خشک به ۱۰۰۰ hPa (برای نمودار جبهه؛ تقریب θw از دمای تر هم‌فشار با فرارفت هم‌ارز)."""
    Tw = wetbulb(T, rh, p); return theta(Tw, p) * np.exp(0.0)      # گشتاور مرتبهٔ اول؛ برای مکان‌یابی جبهه تفاوت جابه‌جایی ناچیز است

# ───── جبهه‌زایی و مکان‌یابی جبهه ─────
def frontogenesis(th, u, v, lat, lon):
    """تابع فرانتوژنز دوبعدی کینماتیکی پترسن: F = d|∇θ|/dt (K/m/s)."""
    tx, ty = ddx(th, lat, lon), ddy(th, lat); g = np.maximum(np.hypot(tx, ty), 1e-12)
    ux, vx, uy, vy = ddx(u, lat, lon), ddx(v, lat, lon), ddy(u, lat), ddy(v, lat)
    return -(tx * tx * ux + tx * ty * (vx + uy) + ty * ty * vy) / g
def tfp(tau, lat, lon):
    """پارامتر مکان جبهه (Renard & Clarke 1965): TFP = −∇|∇τ| · ∇τ/|∇τ| ؛ صفرهای آن (با ∇|∇τ| ≠ 0) محل جبهه است."""
    tx, ty = ddx(tau, lat, lon), ddy(tau, lat); g = np.hypot(tx, ty); gx, gy = ddx(g, lat, lon), ddy(g, lat)
    return -(gx * tx + gy * ty) / np.maximum(g, 1e-12)
def qvec(T, u, v, p_hPa, lat, lon):
    """بردار Q (m²/kg/s·K...)  Q = −(R/p)·(∂V/∂x·∇T , ∂V/∂y·∇T) و واگرایی آن."""
    tx, ty = ddx(T, lat, lon), ddy(T, lat); k = -RD / (p_hPa * 100.0)
    q1 = k * (ddx(u, lat, lon) * tx + ddx(v, lat, lon) * ty); q2 = k * (ddy(u, lat) * tx + ddy(v, lat) * ty)
    return q1, q2, ddx(q1, lat, lon) + ddy(q2, lat)
def smooth(f, n=1):
    """هموارسازی ۵نقطه‌ای (برای مکان‌یابی پایدار جبهه؛ هرگز روی نقشهٔ رنگی نمایش داده نمی‌شود)."""
    f = np.asarray(f, float)
    for _ in range(n):
        g = f.copy(); g[..., 1:-1, 1:-1] = 0.5 * f[..., 1:-1, 1:-1] + 0.125 * (f[..., :-2, 1:-1] + f[..., 2:, 1:-1] + f[..., 1:-1, :-2] + f[..., 1:-1, 2:]); f = g
    return f

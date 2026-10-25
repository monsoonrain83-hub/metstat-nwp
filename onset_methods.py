#!/usr/bin/env python3
"""روش‌های آغاز و پایان فصل بارش روی دادهٔ روزانه (برداری روی همهٔ سلول‌ها).
ورودی هر روش: p = آرایهٔ (T, N) بارش روزانه (mm) برای یک «سال آبی» از ۱ اوت تا ۳۱ ژوئیه (T=365؛ ۲۹ فوریه حذف شده)،
              و دیکشنری پارامتر. خروجی: (onset, cess) دو آرایهٔ int16 به طول N؛ مقدار = شمارندهٔ روز از ۱ اوت (۰ = ۱ اوت)، و -1 = تعریف نشد/پیدا نشد.
هر عدد آستانه‌ای که در منبع پیدا نشده با ⚠ مشخص شده و در پارامترها قابل تغییر است (workflow ورودی می‌گیرد)؛ هیچ آستانه‌ای مخفیانه حدس زده نشده.
منابع: Sivakumar 1988 · Camberlin & Diop 2003 · Moron et al. 2008 · Ferijal et al. 2022 · ACMAD-AGRHYMET (PRESAO 1998) · دانشگاه زنجان («شناسایی فصل بارش در ایران»).
"""
import numpy as np

T = 365
# شمارندهٔ روز (از ۱ اوت) برای تاریخ‌های مرجع: اوت 31، سپتامبر 30، اکتبر 31، نوامبر 30، دسامبر 31، ژانویه 31، فوریه 28
D_OCT1, D_NOV1, D_MAR1, D_APR1 = 61, 92, 212, 243

# ───────── پارامتر پیش‌فرض (همه قابل تغییر) ─────────
PARAMS = {
    "siv": dict(  # Sivakumar (1988)، به نقل از arXiv:2106.12571
        win=3, amt=20.0, look=30, dry_len=8,           # ≥۲۰mm در ۳ روز، بدون ≥۸ روز خشک ("بیش از ۷ روز") در ۳۰ روز بعد
        dry_mm=1.0,                                      # ⚠ آستانهٔ «روز خشک» در متن یافت‌شده نبود؛ ۱mm (روز بارانی WMO) فرض شد
        on_from=15, on_to=D_APR1 + 29,                   # ⚠ بازهٔ جستجوی آغاز (مقاله برای غرب آفریقا از ۱ می است؛ برای ایران ۱۵ اوت تا پایان آوریل)
        cs_from=D_MAR1, cs_dry=20, cs_mm=5.0),           # پایان: ۲۰ روز پیاپی بدون بارش ≥۵mm؛ ⚠ آغاز جستجوی پایان ۱ مارس (مقاله: ۱ سپتامبر)
    "cam": dict(  # Camberlin & Diop (2003)
        win=2, amt=20.0, look=30, dry_len=7, dry_mm=1.0,   # ⚠ dry_mm همان فرض ۱mm
        on_from=15, on_to=D_APR1 + 29, cs_from=D_MAR1, cs_dry=7),  # پایان: ≥۷ روز خشک پیاپی (⚠ برای اقلیم بارش زمستانه زود فعال می‌شود)
    "mor": dict(  # Moron, Robertson & Boer (2008)
        win=5, amt=40.0, look=30, sub=10, sub_mm=5.0,    # ≥۴۰mm در ۵ روز، و هیچ پنجرهٔ ۱۰روزهٔ با مجموع <۵mm در ۳۰ روز بعد
        on_from=15, on_to=D_APR1 + 29),                  # پایان در مقاله تعریف نشده
    "fer": dict(  # Ferijal et al. (2022)، روش زراعی
        wet_days=3, amt=40.0, win=30, dry_len=10, dry_mm=5.0,
        wet_mm=5.0,                                       # ⚠ آستانهٔ «روز تر» در متن یافت‌شده نبود؛ هم‌اندازهٔ آستانهٔ خشک (۵mm) فرض شد
        on_from=15, on_to=D_APR1 + 29, cs_from=D_MAR1),
    "cum": dict(on_from=0, on_to=T - 1),                 # ناهنجاری انباشته (Liebmann/Ferijal): بیشترین صعود؛ بدون آستانه
    "irn": dict(ma=30, min_run=30),                      # ایران: میانگین متحرک ۳۰ روزه > میانگین بلندمدت، دنبالهٔ ≥۳۰ روز (⚠ جزئیات از چکیدهٔ مقاله)
    "prs": dict(store=70.0, et=5.0, start=D_OCT1, cs_from=D_MAR1),  # PRESAO: ظرفیت ۷۰mm، تبخیر‌تعرق ۵mm/روز؛ ⚠ شروع بیلان ۱ اکتبر با خاک خشک
}

def _cs(a):
    """مجموع تجمعی با صفر ابتدایی: cs[k]=sum(a[:k])"""
    o = np.zeros((a.shape[0] + 1,) + a.shape[1:], dtype=np.float64); np.cumsum(a, axis=0, out=o[1:]); return o

def _wsum(cs, k):
    """مجموع پنجرهٔ k‌روزهٔ آغاز‌شونده از t: (T,N)؛ پنجره‌های ناقص (به انتهای سال خورده) NaN"""
    n = cs.shape[0] - 1; w = cs[k:] - cs[:-k]; out = np.full((n,) + cs.shape[1:], np.nan); out[:n - k + 1] = w; return out

def _run_all(flag, k):
    """True در t اگر flag برای k روز متوالی از t به بعد True باشد (کاملاً داخل سال)."""
    w = _wsum(_cs(flag.astype(np.float64)), k); return np.nan_to_num(w, nan=0.0) >= k

def _any_in(flag, a_off, b_off):
    """برای هر t آیا flag در بازهٔ [t+a_off, t+b_off] (شامل) حداقل یک‌بار True است؟ خارج از سال = False"""
    n = flag.shape[0]; cs = _cs(flag.astype(np.float64)); t = np.arange(n)[:, None]
    lo = np.clip(t + a_off, 0, n); hi = np.clip(t + b_off + 1, 0, n)
    return (np.take_along_axis(cs, np.broadcast_to(hi, flag.shape), 0) - np.take_along_axis(cs, np.broadcast_to(lo, flag.shape), 0)) > 0

def _first(cond, lo, hi):
    """اولین t در [lo,hi] که cond True است؛ وگرنه -1"""
    c = cond.copy(); c[:max(0, lo)] = False; c[hi + 1:] = False
    ok = c.any(axis=0); idx = np.argmax(c, axis=0).astype(np.int16); idx[~ok] = -1; return idx

def _last_flag_before(flag, t_idx):
    """آخرین t' < t_idx با flag True برای هر سلول (برداری)؛ اگر نبود -1"""
    n = flag.shape[0]; pos = np.where(flag, np.arange(n)[:, None], -1); ff = np.maximum.accumulate(pos, axis=0)
    out = np.full(t_idx.shape, -1, dtype=np.int16); ok = t_idx > 0
    cols = np.where(ok)[0]; out[cols] = ff[t_idx[cols] - 1, cols]; return out

def _nan_cells(p):
    return np.isnan(p).any(axis=0)

# ───────── روش‌ها ─────────
def m_siv(p, q=None):
    P = {**PARAMS["siv"], **(q or {})}; bad = _nan_cells(p); x = np.nan_to_num(p)
    dry = x < P["dry_mm"]; ws = _wsum(_cs(x), P["win"]); cond = np.nan_to_num(ws, nan=0) >= P["amt"]
    # دورهٔ خشکِ ≥dry_len روز کاملاً داخل ۳۰ روز بعد از روز آغاز [d, d+look-1]
    run = _run_all(dry, P["dry_len"]); spell = _any_in(run, 0, P["look"] - P["dry_len"])
    on = _first(cond & ~spell, P["on_from"], P["on_to"])
    wet5 = x >= P["cs_mm"]; gap = _run_all(~wet5, P["cs_dry"]); d = _first(gap, P["cs_from"], T - 1)
    cs = np.where(d >= 0, np.maximum(_last_flag_before(wet5, d.astype(np.int64)), 0), -1).astype(np.int16)
    cs[(d >= 0) & (_last_flag_before(wet5, d.astype(np.int64)) < 0)] = d[(d >= 0) & (_last_flag_before(wet5, d.astype(np.int64)) < 0)]
    on[bad] = -1; cs[bad] = -1; return on, cs

def m_cam(p, q=None):
    P = {**PARAMS["cam"], **(q or {})}; bad = _nan_cells(p); x = np.nan_to_num(p)
    dry = x < P["dry_mm"]; ws = _wsum(_cs(x), P["win"]); cond = np.nan_to_num(ws, nan=0) >= P["amt"]
    run = _run_all(dry, P["dry_len"]); spell = _any_in(run, 0, P["look"] - P["dry_len"])
    on = _first(cond & ~spell, P["on_from"], P["on_to"]); cs = _first(run, P["cs_from"], T - 1)
    on[bad] = -1; cs[bad] = -1; return on, cs

def m_mor(p, q=None):
    P = {**PARAMS["mor"], **(q or {})}; bad = _nan_cells(p); x = np.nan_to_num(p)
    ws = _wsum(_cs(x), P["win"]); cond = np.nan_to_num(ws, nan=0) >= P["amt"]
    s10 = _wsum(_cs(x), P["sub"]); low = np.nan_to_num(s10, nan=1e9) < P["sub_mm"]; spell = _any_in(low, 0, P["look"] - P["sub"])
    on = _first(cond & ~spell, P["on_from"], P["on_to"]); cs = np.full(x.shape[1], -1, dtype=np.int16); on[bad] = -1; return on, cs

def m_fer(p, q=None):
    P = {**PARAMS["fer"], **(q or {})}; bad = _nan_cells(p); x = np.nan_to_num(p)
    wet = x >= P["wet_mm"]; dry = x < P["dry_mm"]; nw = _wsum(_cs(wet.astype(np.float64)), P["win"]); sm = _wsum(_cs(x), P["win"])
    cond = wet & (np.nan_to_num(nw, nan=0) >= P["wet_days"]) & (np.nan_to_num(sm, nan=0) >= P["amt"])
    run = _run_all(dry, P["dry_len"]); spell = _any_in(run, 0, P["win"] - P["dry_len"])
    on = _first(cond & ~spell, P["on_from"], P["on_to"])
    d = _first(run, P["cs_from"], T - 1); last = _last_flag_before(wet, d.astype(np.int64)); cs = np.where(d >= 0, np.where(last >= 0, last, d), -1).astype(np.int16)
    on[bad] = -1; cs[bad] = -1; return on, cs

def m_cum(p, q=None):
    """بیشترین صعود مجموع انباشتهٔ (بارش − میانگین روزانهٔ همان سال)؛ آغاز = روز بعد از کمینه، پایان = روز اوج."""
    P = {**PARAMS["cum"], **(q or {})}; bad = _nan_cells(p); x = np.nan_to_num(p); a = np.cumsum(x - x.mean(axis=0), axis=0)
    runmin = np.minimum.accumulate(a, axis=0); pos = np.where(a <= runmin, np.arange(T)[:, None], 0); imin = np.maximum.accumulate(pos, axis=0)
    rise = a - runmin; tmax = np.argmax(rise, axis=0); cols = np.arange(x.shape[1])
    on = np.minimum(imin[tmax, cols] + 1, T - 1).astype(np.int16); cs = tmax.astype(np.int16)
    flat = (x.sum(axis=0) <= 0) | (rise[tmax, cols] <= 0); on[flat | bad] = -1; cs[flat | bad] = -1; return on, cs

def m_irn(p, q=None, thr=None):
    """ایران (دانشگاه زنجان): میانگین متحرک ۳۰ روزه > آستانه (میانگین بلندمدت بارش روزانه، thr (N,)). بلندترین دنبالهٔ ≥۳۰ روز."""
    P = {**PARAMS["irn"], **(q or {})}; bad = _nan_cells(p); x = np.nan_to_num(p); n = x.shape[1]
    if thr is None: thr = x.mean(axis=0)
    cs = _cs(x); k = P["ma"]; h = k // 2; ma = np.full(x.shape, np.nan)
    for t in range(T):
        a = t - h; b = a + k
        if a < 0 or b > T: continue
        ma[t] = (cs[b] - cs[a]) / k
    above = np.nan_to_num(ma, nan=-1) > thr[None, :]
    best = np.zeros(n, dtype=np.int32); bs = np.full(n, -1, dtype=np.int32); be = np.full(n, -1, dtype=np.int32); cur = np.zeros(n, dtype=np.int32)
    for t in range(T):
        cur = np.where(above[t], cur + 1, 0); upd = cur > best; best = np.where(upd, cur, best); be = np.where(upd, t, be); bs = np.where(upd, t - cur + 1, bs)
    ok = best >= P["min_run"]; on = np.where(ok, bs, -1).astype(np.int16); cs_ = np.where(ok, be, -1).astype(np.int16)
    on[bad] = -1; cs_[bad] = -1; return on, cs_

def m_prs(p, q=None):
    """PRESAO: پایان = روزی (از ۱ مارس به بعد) که ذخیرهٔ آب خاک (ظرفیت ۷۰mm، تبخیر‌تعرق روزانهٔ ثابت) تمام می‌شود؛ آغاز تعریف نشده."""
    P = {**PARAMS["prs"], **(q or {})}; bad = _nan_cells(p); x = np.nan_to_num(p); s = np.zeros(x.shape[1]); cs = np.full(x.shape[1], -1, dtype=np.int16)
    for t in range(P["start"], T):
        s = np.clip(s + x[t] - P["et"], 0, P["store"])
        if t >= P["cs_from"]: hit = (s <= 0) & (cs < 0); cs[hit] = t
    on = np.full(x.shape[1], -1, dtype=np.int16); cs[bad] = -1; return on, cs

METHODS = {
    "siv": (m_siv, "Sivakumar (1988) — زراعی", "Sivakumar (1988) — agronomic", True, True),
    "cam": (m_cam, "Camberlin و Diop (2003) — زراعی", "Camberlin & Diop (2003) — agronomic", True, True),
    "mor": (m_mor, "Moron و همکاران (2008) — زراعی", "Moron et al. (2008) — agronomic", True, False),
    "fer": (m_fer, "Ferijal و همکاران (2022) — زراعی", "Ferijal et al. (2022) — agronomic", True, True),
    "cum": (m_cum, "ناهنجاری انباشته (Liebmann)", "Cumulative anomaly (Liebmann)", True, True),
    "irn": (m_irn, "میانگین متحرک ۳۰ روزه (ایران)", "30-day moving average (Iran)", True, True),
    "prs": (m_prs, "بیلان آب خاک (PRESAO)", "Soil-water balance (PRESAO)", False, True),
}

def water_year_array(daily, dates_year0):
    """daily: (ndays, N) از ۱ اوت سال y0 تا ۳۱ ژوئیه سال بعد (۳۶۵ یا ۳۶۶ روز)؛ ۲۹ فوریه را حذف می‌کند."""
    import datetime as dt
    n = daily.shape[0]; d0 = dt.date(dates_year0, 8, 1); keep = [i for i in range(n) if not ((d0 + dt.timedelta(days=i)).month == 2 and (d0 + dt.timedelta(days=i)).day == 29)]
    out = daily[keep]; assert out.shape[0] == T, out.shape; return out

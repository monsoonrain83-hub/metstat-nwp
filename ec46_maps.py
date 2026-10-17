#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ECMWF EC46 (۴۶ روزه): میانگین اعضای مجموعه از Open-Meteo seasonal API (مدل ecmwf_ec46_ensemble_mean) روی شبکهٔ نقطه‌ای،
تبدیل به نقشهٔ روزانه (بارش ۲۴ ساعته، بارش تجمعی، دمای میانگین) و آپلود به همان میزبان نمایشگر (tclass=ens).
نیاز: کنار ens_maps.py و nwp_maps.py اجرا شود.  python3 ec46_maps.py --host https://wtafkik.ir/online --key KEY   (یا --out DIR / --mock)"""
import argparse, math, sys, time
from datetime import datetime, timedelta, timezone
import numpy as np, requests
import ens_maps as E, nwp_maps as N
UTC = timezone.utc; log = N.log
API = 'https://seasonal-api.open-meteo.com/v1/seasonal'
STEP = 1.5; LO0, LO1, LA0, LA1 = E.CROP
E.MODELS['ec46c'] = dict(label='ECMWF EC46 — کنترل (۴۶ روزه)', name='ECMWF-EC46-CTRL', res='~0.25° (نقطه‌ای ۱٫۵°)', cyc='00 (روزانه)', prov='ECMWF EC46 · Open-Meteo (CC BY 4.0)', src='om', mean=False, days=46)
E.MODELS['ec46m'] = dict(label='ECMWF EC46 — میانگین اعضا (۴۶ روزه)', name='ECMWF-EC46-MEAN', res='~0.25° (نقطه‌ای ۱٫۵°)', cyc='00 (روزانه)', prov='ECMWF EC46 · Open-Meteo (CC BY 4.0)', src='om', mean=True, days=46)
E.PARAMS = {k: v for k, v in E.PARAMS.items() if k != 'z500a'}

def fetch(lats, lons, tries=3, model='ecmwf_ec46_ensemble_mean'):
    p = dict(latitude=','.join(f'{x:.2f}' for x in lats), longitude=','.join(f'{x:.2f}' for x in lons), models=model,
             daily='precipitation_sum,temperature_2m_mean', forecast_days=46, timezone='GMT')
    for k in range(tries):
        try:
            r = requests.get(API, params=p, timeout=240)
            if r.status_code == 200:
                j = r.json(); return j if isinstance(j, list) else [j]
            log(f'  HTTP {r.status_code}: {r.text[:140]}')
        except Exception as e: log(f'  {type(e).__name__} (تلاش {k + 1})')
        time.sleep(4 * (k + 1))
    return None

def collect(mock=False, model='ecmwf_ec46_ensemble_mean'):
    lo = np.arange(LO0, LO1 + 1e-6, STEP); la = np.arange(LA0, LA1 + 1e-6, STEP)
    LON, LAT = np.meshgrid(lo, la); fl, fa = LON.ravel(), LAT.ravel(); n = len(fl); nd = 46
    if mock:
        rng = np.random.default_rng(3); t0 = datetime(2026, 10, 15, tzinfo=UTC)
        pr = np.maximum(np.sin(LON[None] / 6 + np.arange(nd)[:, None, None] * .5) * 6 + rng.normal(0, 1, (nd,) + LON.shape), 0).astype(np.float32)
        tm = (22 + 12 * np.cos(np.radians(LAT - 25) * 2))[None].repeat(nd, 0).astype(np.float32)
        return t0, lo, la, pr, tm
    pr = np.full((nd, n), np.nan, np.float32); tm = pr.copy(); t0 = None; B = 25
    def do(s):
        nonlocal t0
        res = fetch(fa[s:s + B], fl[s:s + B], tries=4, model=model)
        if not res: return False
        for i, o in enumerate(res):
            d = o.get('daily') or {}; t = d.get('time') or []
            if not t: continue
            if t0 is None: t0 = datetime.strptime(t[0], '%Y-%m-%d').replace(tzinfo=UTC)
            for arr, key in ((pr, 'precipitation_sum'), (tm, 'temperature_2m_mean')):
                v = d.get(key)
                if v: arr[:len(v), s + i] = np.array([np.nan if x is None else x for x in v], np.float32)
        return True
    failed = [s for s in range(0, n, B) if not do(s) or time.sleep(1.0)]
    for rnd in range(3):                                   # دورهای دوباره برای دسته‌های ناموفق
        if not failed: break
        log(f'↻ دور {rnd + 1}: {len(failed)} دسته دوباره'); time.sleep(20); failed = [s for s in failed if not do(s)]
    miss = float(np.mean(~np.isfinite(pr[0]))) if n else 1
    if failed or miss > 0.02:
        log(f'✗ EC46: {len(failed)} دسته دریافت نشد ({miss * 100:.1f}٪ نقاط خالی)؛ برای جلوگیری از نقشهٔ حفره‌دار چیزی آپلود نشد'); return None
    if t0 is None or not np.isfinite(pr).any(): return None
    return t0, lo, la, pr.reshape((nd,) + LON.shape), tm.reshape((nd,) + LON.shape)

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--host'); ap.add_argument('--key', default=''); ap.add_argument('--out'); ap.add_argument('--mock', action='store_true')
    a = ap.parse_args()
    if not a.host and not a.out: sys.exit('--host یا --out لازم است')
    if a.mock: N.z500_clim_at = lambda R, d: None
    up = N.Uploader(a.host, a.key, a.out)
    for mk, om in (('ec46m', 'ecmwf_ec46_ensemble_mean'), ('ec46c', 'ecmwf_ec46')):
        if mk == 'ec46c' and a.mock: continue
        R = collect(a.mock, om)
        if not R: log(f'✗ {mk}: داده‌ای از Open-Meteo گرفته نشد'); continue
        t0, lo, la, pr, tm = R; log(f'▶ {mk}: شروع {t0:%Y-%m-%d} ، {pr.shape[0]} روز')
        prods = {}; cum = np.zeros(pr.shape[1:], np.float32)
        for k in range(1, pr.shape[0] + 1):
            p = pr[k - 1]
            if not np.isfinite(p).any(): continue
            cum = cum + np.nan_to_num(p); o = dict(p24=(np.maximum(p, 0), lo, la), ptot=(cum.copy(), lo, la))
            if np.isfinite(tm[k - 1]).any(): o['t2m'] = (tm[k - 1], lo, la)
            prods[k] = o
        n = E.make_model(up, mk, t0, prods, a); log(f'پایان {mk}: {n} نقشه')
    sys.exit(0)

if __name__ == '__main__': main()

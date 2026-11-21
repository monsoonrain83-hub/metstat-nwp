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
E.MODELS['ec46m'] = dict(label='ECMWF EC46 — میانگین اعضا (۴۶ روزه؛ بارش: PMM)', name='ECMWF-EC46-MEAN', res='~0.25° (نقطه‌ای ۱٫۵°)', cyc='00 (روزانه)', prov='ECMWF EC46 · Open-Meteo (CC BY 4.0)', src='om', mean=True, days=46)
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
    pr = np.full((nd, n), np.nan, np.float32); tm = pr.copy(); t0 = None; B = 25; MEM = {}
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
            for kk, vv in d.items():                      # r102g: اعضای جدا (در صورت وجود) برای PMM
                if kk.startswith('precipitation_sum_member') and vv:
                    MEM.setdefault(kk, np.full((nd, n), np.nan, np.float32))[:len(vv), s + i] = np.array([np.nan if x is None else x for x in vv], np.float32)
        return True
    failed = [s for s in range(0, n, B) if not do(s) or time.sleep(1.0)]
    for rnd in range(3):                                   # دورهای دوباره برای دسته‌های ناموفق
        if not failed: break
        log(f'↻ دور {rnd + 1}: {len(failed)} دسته دوباره'); time.sleep(20); failed = [s for s in failed if not do(s)]
    miss = float(np.mean(~np.isfinite(pr[0]))) if n else 1
    if failed or miss > 0.02:
        log(f'✗ EC46: {len(failed)} دسته دریافت نشد ({miss * 100:.1f}٪ نقاط خالی)؛ برای جلوگیری از نقشهٔ حفره‌دار چیزی آپلود نشد'); return None
    if t0 is None or not np.isfinite(pr).any(): return None
    collect.members = [m_.reshape((nd,) + LON.shape) for m_ in MEM.values()]
    return t0, lo, la, pr.reshape((nd,) + LON.shape), tm.reshape((nd,) + LON.shape)

def weekly_values(pr,tm,week_index):
    a,b=week_index*7,(week_index+1)*7
    if b>min(pr.shape[0],tm.shape[0]):return None
    if min(float(np.isfinite(pr[a:b]).all(axis=0).mean()),float(np.isfinite(tm[a:b]).all(axis=0).mean()))<.95:
        return None
    return (np.maximum(np.nansum(pr[a:b],axis=0),0).astype(np.float32),
            np.nanmean(tm[a:b],axis=0).astype(np.float32))

def publish_weekly_absolute(up, run, lo, la, pr, tm):
    """Seven-day totals/means from actual EC46 daily forecasts.
    These are ABSOLUTE predictions, never represented as anomalies.
    """
    import wk_maps as W
    W.MODELS['ecwkabs'] = dict(label='ECMWF EC46 — هفتگی: بارش و دمای مطلق (نه آنومالی)',
                              name='ECMWF-EC46-WEEKLY-ABS',res='نمونه‌برداری ۱٫۵ درجه؛ درون‌یابی صرفاً برای نمایش',
                              cyc='روزانه',prov='ECMWF EC46 · Open-Meteo (CC BY 4.0)',tclass='weekly')
    W.PARAMS['wp7'] = ('بارش تجمعی هفت‌روزه EC46 (میلی‌متر، مطلق)', 'mm','pr',11,E.PARAMS['p24'][4])
    W.PARAMS['wtm'] = ('میانگین هفتگی دمای ۲ متر EC46 (درجه سلسیوس، مطلق)','°C','tp',21,E.PARAMS['t2m'][4])
    W.MPAR['ecwkabs'] = ('wp7','wtm')
    begin=W.begin(up,'ecwkabs',run)
    if str(begin.get('run'))!=f'{run:%Y%m%d%H}':
        raise RuntimeError('weekly EC46 host begin failed: '+str(begin)[:160])
    have=set(begin.get('have',[]))
    made=0
    for w in range(min(pr.shape[0],tm.shape[0])//7):
        aggregate=weekly_values(pr,tm,w)
        if aggregate is None:
            log(f'  ✗ EC46 weekly absolute {w+1}: incomplete daily source, skip 7-day aggregation')
            continue
        rain,temp=aggregate
        vt=run+timedelta(days=(w+1)*7)
        b=(w+1)*7
        for pid,value in (('wp7',rain),('wtm',temp)):
            field=E.L.regrid(value,lo,la)
            made+=W.put(up,'ecwkabs',run,pid,vt,24*b,field,have)
    up.wait()
    ended=up.call('end',js={'model':'ecwkabs','run':f'{run:%Y%m%d%H}'})
    if not ended.get('ok'):raise RuntimeError('weekly EC46 host end failed: '+str(ended)[:200])
    log(f'✓ ECMWF EC46 weekly absolute (NOT anomalies): {made} new maps')
    return made

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--host'); ap.add_argument('--key', default=''); ap.add_argument('--out'); ap.add_argument('--mock', action='store_true')
    a = ap.parse_args()
    if not a.host and not a.out: sys.exit('--host یا --out لازم است')
    if a.mock: N.z500_clim_at = lambda R, d: None
    up = N.Uploader(a.host, a.key, a.out)
    MEMB = []; failed=[]; total_maps = 0
    for mk, om in (('ec46c', 'ecmwf_ec46'), ('ec46m', 'ecmwf_ec46_ensemble_mean')):
        if mk == 'ec46c' and a.mock: continue
        R = collect(a.mock, om)
        if not R: failed.append(mk); log(f'✗ {mk}: داده‌ای از Open-Meteo گرفته نشد'); continue
        t0, lo, la, pr, tm = R; log(f'▶ {mk}: شروع {t0:%Y-%m-%d} ، {pr.shape[0]} روز')
        if mk == 'ec46c': MEMB = list(getattr(collect, 'members', []) or []); log(f'  اعضای جدا در پاسخ Open-Meteo: {len(MEMB)}')
        usepmm = mk == 'ec46m' and len(MEMB) >= 10
        if mk == 'ec46m': log('  PMM فعال (توزیع شدت از %d عضو)' % len(MEMB) if usepmm else '  ⚠ اعضای جدا در دسترس نیست؛ میانگین ساده (هموار) نمایش داده می‌شود')
        prods = {}; cum = np.zeros(pr.shape[1:], np.float32)
        for k in range(1, pr.shape[0] + 1):
            p = pr[k - 1]
            if not np.isfinite(p).any(): continue
            if usepmm: p = E.pmm(p, [m_[k - 1] for m_ in MEMB])
            cum = cum + np.nan_to_num(p); o = dict(p24=(np.maximum(p, 0), lo, la), ptot=(cum.copy(), lo, la))
            if np.isfinite(tm[k - 1]).any(): o['t2m'] = (tm[k - 1], lo, la)
            prods[k] = o
        n = E.make_model(up, mk, t0, prods, a); total_maps += n; log(f'پایان {mk}: {n} نقشه')
        if mk == 'ec46m':
            try: publish_weekly_absolute(up,t0,lo,la,pr,tm)
            except Exception as exc: failed.append('ecwkabs'); log(f'✗ EC46 هفتگی مطلق: {exc}')
    if total_maps == 0 and not a.mock:
        failed.append('no-new-ec46-maps')
        log('✗ EC46: هیچ نقشه تازه‌ای تولید نشد؛ نتیجه موفق گزارش نمی‌شود')
    if failed: log('✗ پردازش ناقص: '+','.join(failed))
    sys.exit(2 if failed else 0)

if __name__ == '__main__': main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MetStat — مدل NAVGEM (نیروی دریایی آمریکا، FNMOC) برای تب «روزانه»
  منبع: NOMADS  https://nomads.ncep.noaa.gov/pub/data/nccf/com/fnmoc/prod/navgem.YYYYMMDD/navgem_YYYYMMDDHHfNNN.grib2   (۰٫۵°، حدود ۷٫۵ روز، بدون .idx → کل فایل دانلود می‌شود)
  پارامترها (هم‌شناسه با بقیهٔ مدل‌های روزانه): p6 (بارش ۶ ساعته)، p24 (۲۴ ساعته)، pacc (تجمعی از ابتدای اجرا)، t2m (دمای ۲ متری)
  تذکر صادقانه: NAVGEM فقط مدل میان‌مدت است؛ نسخهٔ هفتگی/ماهانه/فصلی واقعی ندارد. «بارش تجمعی از ابتدای اجرا» همان جمع ~۷ روزه است.
  آزمایشی: نام متغیرهای GRIB (tp/2t) و واحد تجمعی (۰–۶ ساعته یا از ابتدا) با startStep/endStep تشخیص داده می‌شود؛ بدون شبکهٔ سندباکس فقط با --mock آزموده شد.
اجرا: python navgem_maps.py --host https://wtafkik.ir/online --key KEY   |   --mock --out out"""
import argparse, json, math, os, re, sys, tempfile, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import numpy as np
import nwp_maps as N, styles, lr_maps as L
import ens_maps as E

UTC = timezone.utc; log = N.log
NOMADS = 'https://nomads.ncep.noaa.gov/pub/data/nccf/com/fnmoc/prod'
MKEY = 'navgem'
M = dict(name='NAVGEM', label='NAVGEM (US Navy) 0.5°', res='0.5°', cyc='00/06/12/18', prov='US Navy FNMOC via NOMADS')
PIDS = ('t2m', 'w10', 'z500a')      # فایل‌های عمومی NAVGEM بارش ندارند (فهرست فیلدها در لاگ)
PMETA = {'t2m': None, 'w10': dict(fa='سرعت باد ۱۰ متری (گره)', unit='kt', cat='sf', ord=112, sc='wind10', ln=0), 'z500a': None}

def http_list(day):
    import requests
    u = f'{NOMADS}/navgem.{day:%Y%m%d}/'
    r = requests.get(u, timeout=60)
    if r.status_code != 200: return {}
    out = {}
    for run, ld in re.findall(r'navgem_(\d{10})f(\d{3})\.grib2', r.text): out.setdefault(run, set()).add(int(ld))
    return out

def pick_run():
    now = datetime.now(UTC)
    for dd in (0, 1, 2):
        for run, leads in sorted(http_list(now - timedelta(days=dd)).items(), reverse=True):
            if 0 in leads and max(leads) >= 168 and len([x for x in leads if x % 6 == 0]) >= 28: return datetime.strptime(run, '%Y%m%d%H').replace(tzinfo=UTC), sorted(leads)
    return None, []

def read_file(url, ld_=None):
    """کل فایل را دانلود و (tp, 2t) را می‌خواند → {'tp': (start, end, arr, lo, la), 't2': (arr, lo, la)}"""
    import requests, eccodes as EC
    fd, path = tempfile.mkstemp(suffix='.grib2'); os.close(fd)
    try:
        for k in range(4):
            try:
                with requests.get(url, stream=True, timeout=120) as r:
                    r.raise_for_status()
                    with open(path, 'wb') as f:
                        for ch in r.iter_content(1 << 20): f.write(ch)
                break
            except Exception as e:
                if k == 3: raise
                time.sleep(4 * (k + 1))
        res = {}; inv = set()
        with open(path, 'rb') as f:
            while True:
                g = EC.codes_grib_new_from_file(f)
                if g is None: break
                try:
                    sn = EC.codes_get(g, 'shortName'); tl = EC.codes_get(g, 'typeOfLevel')
                    try: inv.add((sn, EC.codes_get(g, 'name'), tl, EC.codes_get(g, 'level'), EC.codes_get(g, 'units')))
                    except Exception: pass
                    PA, PR = ('tp', 'apcp'), ('prate', 'tprate')            # تجمعی (mm) یا نرخ (kg/m2/s)
                    if (sn in PA or sn in PR) and 'tp' not in res:
                        msg = EC.codes_get_message(g); arr, lo, la = E.decode(msg); st_, en_ = EC.codes_get(g, 'startStep'), EC.codes_get(g, 'endStep')
                        if sn in PR: arr = arr * 21600.0; st_, en_ = max(0, (ld_ or 6) - 6), (ld_ or 6)       # نرخ لحظه‌ای × ۶ ساعت (تقریب)
                        res['tp'] = (st_, en_, arr, lo, la)
                    elif sn in ('10u', '10v') and sn not in res:
                        msg = EC.codes_get_message(g); arr, lo, la = E.decode(msg); res[sn] = (arr, lo, la)
                    elif sn == 'gh' and tl == 'isobaricInhPa' and EC.codes_get(g, 'level') == 500 and 'z5' not in res:
                        msg = EC.codes_get_message(g); arr, lo, la = E.decode(msg); res['z5'] = (arr, lo, la)
                    elif sn in ('2t', 't') and tl in ('heightAboveGround',) and EC.codes_get(g, 'level') == 2 and 't2' not in res:
                        msg = EC.codes_get_message(g); arr, lo, la = E.decode(msg); res['t2'] = (arr, lo, la)
                finally: EC.codes_release(g)
        if not INV_LOGGED and inv:
            INV_LOGGED.append(1); log('  فهرست فیلدهای فایل NAVGEM: ' + ' | '.join(f'{a}/{b}/{c}/{d}/{e}' for a, b, c, d, e in sorted(inv, key=str)))
        return res
    finally:
        try: os.remove(path)
        except Exception: pass

INV_LOGGED = []
def collect(run, leads):
    ls = [x for x in leads if x % 6 == 0 and x <= 192]
    def job(ld):
        u = f'{NOMADS}/navgem.{run:%Y%m%d}/navgem_{run:%Y%m%d%H}f{ld:03d}.grib2'
        try: return ld, read_file(u, ld)
        except Exception as e: log(f'  ✗ f{ld:03d}: {type(e).__name__}: {e}'); return ld, {}
    with ThreadPoolExecutor(4) as ex: R = dict(ex.map(job, ls))
    cum = {0: None}; t2 = {}; inc = {}
    for ld in sorted(R):
        r = R[ld]
        if 't2' in r: t2[ld] = r['t2']
        if 'tp' in r:
            st, en, a, lo, la = r['tp']; a = np.nan_to_num(a, nan=0.0)
            if ld == 0: continue
            prev = cum.get(ld - 6)
            if st == 0 and en == ld: cum[ld] = (a, lo, la); inc[ld] = (a - prev[0] if prev else a, lo, la) if prev is not None or ld == 6 else None
            else:
                if prev is None and ld != 6: continue
                tot = a + (prev[0] if prev else 0); cum[ld] = (tot, lo, la); inc[ld] = (a, lo, la)
    ex = {}
    for ld, r in R.items():
        o = {}
        if '10u' in r and '10v' in r: o['w10'] = (np.hypot(r['10u'][0], r['10v'][0]) * 1.943844, r['10u'][1], r['10u'][2])
        if 'z5' in r: o['z5'] = r['z5']
        if o: ex[ld] = o
    return cum, inc, t2, ex

def products(cum, inc, t2, ex=None):
    P = {}
    for ld in sorted(x for x in cum if x):
        o = {}
        if inc.get(ld): o['p6'] = (np.maximum(inc[ld][0], 0), inc[ld][1], inc[ld][2])
        o['pacc'] = (np.maximum(cum[ld][0], 0), cum[ld][1], cum[ld][2])
        if ld >= 24 and (ld - 24) in cum or ld == 24: o['p24'] = (np.maximum(cum[ld][0] - (cum[ld - 24][0] if ld > 24 else 0), 0), cum[ld][1], cum[ld][2])
        if ld in t2: o['t2m'] = (t2[ld][0] - 273.15, t2[ld][1], t2[ld][2])
        P[ld] = o
    for ld in t2:
        if ld not in P: P[ld] = {'t2m': (t2[ld][0] - 273.15, t2[ld][1], t2[ld][2])}
    for ld, o in (ex or {}).items(): P.setdefault(ld, {}).update(o)
    return P

def mock():
    rng = np.random.default_rng(3); la = np.arange(E.CROP[2], E.CROP[3] + 0.1, 0.5); lo = np.arange(E.CROP[0], E.CROP[1] + 0.1, 0.5)
    X, Y = np.meshgrid(lo, la); cum = {}; inc = {}; t2 = {}; c = 0
    for ld in range(6, 169, 6):
        d = np.maximum(np.sin(X / 6 + ld / 20) * np.cos(Y / 5 - ld / 30) * 5 + rng.normal(0, .3, X.shape), 0).astype(np.float32); c = c + d
        cum[ld] = (c.copy(), lo, la); inc[ld] = (d, lo, la); t2[ld] = ((290 + 12 * np.cos(np.radians(Y - 25) * 2)).astype(np.float32), lo, la)
    return cum, inc, t2

def make(up, run, P):
    rid = f'{run:%Y%m%d%H}'
    def meta(p):
        if p == 'z500a': v = E.PARAMS['z500a']; return dict(fa=v[0], unit=v[1], cat=v[2], o=v[3], sc=v[4], mu=v[1], alt='', me=1, ln=v[5])
        m = PMETA.get(p) or N.PARAMS[p]; return dict(fa=m['fa'], unit=m['unit'], cat=m['cat'], o=m.get('ord', 0), sc=m['sc'], mu=m['unit'], alt='', me=1, ln=0)
    sc = {meta(p)['sc'] for p in PIDS}
    r = up.call('begin', js={'model': MKEY, 'run': rid, 'name': M['name'], 'label': M['label'],
        'info': dict(tclass='daily', res=M['res'], cyc=M['cyc'], prov=M['prov']), 'cats': [dict(id=i, fa=f, o=o) for i, f, o in N.CATS],
        'scales': {k: dict(c=styles.SC[k]['colors'], e=[None if abs(x) == math.inf else x for x in styles.SC[k]['edges']], lo=styles.SC[k]['edges'][0] == -math.inf, hi=styles.SC[k]['edges'][-1] == math.inf) for k in sc},
        'params': {p: meta(p) for p in PIDS}})
    have = set(r.get('have', [])); made = 0
    for ld, o in sorted(P.items()):
        vt = run + timedelta(hours=ld); v = f'{vt:%Y%m%d%H}'
        for pid in PIDS:
            fn = f'me/{pid}_{v}.webp'
            if fn in have: continue
            if pid == 'z500a':
                if 'z5' not in o: continue
                C = N.z500_clim_at(E.G, vt)
                if C is None: continue
                Z = L.regrid(o['z5'][0], o['z5'][1], o['z5'][2])
                dat, lines = N.render_me(None, (Z - C) / 10, 'z500a', cont=Z / 10, cont_lvls=np.arange(480, 620, 4), bold=580)
                up.put(MKEY, rid, fn, dat, dict(r='me', m=MKEY, p=pid, s=ld, v=v)); made += 1
                if lines: up.put(MKEY, rid, f'me/z500aL_{v}.webp', lines, dict(r='me', m=MKEY, p='z500aL', s=ld, v=v))
                continue
            if pid not in o: continue
            f = L.regrid(o[pid][0], o[pid][1], o[pid][2])
            if not np.isfinite(f).any(): continue
            dat, _ = N.render_me(None, f, meta(pid)['sc']); up.put(MKEY, rid, fn, dat, dict(r='me', m=MKEY, p=pid, s=ld, v=v)); made += 1
    up.wait(); up.call('end', js={'model': MKEY, 'run': rid}); log(f'✓ NAVGEM {rid}: {made} نقشهٔ تازه'); return made

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--host'); ap.add_argument('--key', default=''); ap.add_argument('--out'); ap.add_argument('--mock', action='store_true'); a = ap.parse_args()
    if not a.host and not a.out: sys.exit('--host یا --out لازم است')
    up = N.Uploader(a.host, a.key, a.out)
    if a.mock:
        run = datetime.now(UTC).replace(minute=0, second=0, microsecond=0); cum, inc, t2 = mock(); ex = {ld: {'w10': ((np.abs(t2[ld][0] - 285) * 1.5).astype(np.float32), t2[ld][1], t2[ld][2]), 'z5': ((5750 + (t2[ld][0] - 290) * 20).astype(np.float32), t2[ld][1], t2[ld][2])} for ld in t2}
        N.z500_clim_at = lambda R, d: (np.float32(5750) + (R.lat - 30) * -20).astype(np.float32)
    else:
        run, leads = pick_run()
        if not run: log('✗ NAVGEM: اجرای کامل در NOMADS پیدا نشد (فقط ~۲ روز آخر نگه داشته می‌شود)'); sys.exit(0)
        log(f'▶ NAVGEM اجرای {run:%Y-%m-%d %H}Z، {len(leads)} گام'); cum, inc, t2, ex = collect(run, leads)
    P = products(cum, inc, t2, ex)
    if not P: log('✗ NAVGEM: هیچ نقشه‌ای ساخته نشد (نام متغیر یا ساختار GRIB را در لاگ بررسی کنید)'); sys.exit(0)
    make(up, run, P); sys.exit(0)

if __name__ == '__main__': main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MetStat — نقشه‌های «انسمبل»: کنترل و میانگین اعضا (بارش ۲۴ ساعته، دمای میانگین ۲۴ ساعته، ارتفاع ژئوپتانسیل ۵۰۰ و انومالی)
  • ECMWF ENS (دادهٔ باز ECMWF، s3://ecmwf-forecasts، ۰٫۲۵°، ۱۵ روز، ۵۰ عضو + کنترل)      مدل‌ها: ecenc (کنترل)، ecenm (میانگین اعضا)
  • NOAA CFS (s3://noaa-cfs-pds، ۴ عضو، ۴۵ روز، اجرای ۰۰Z)                                   مدل‌ها: cfsc (عضو ۱)، cfsm (میانگین ۴ عضو)
هر نقشه فقط تصویر است (WebP گسسته)، دادهٔ عددی به هاست نمی‌رود.  خواندن GRIB با eccodes و بازهٔ بایتی (.index / .idx) انجام می‌شود.
اجرا:  python ens_maps.py --host https://wtafkik.ir/online --key KEY   |   --mock --out out (آزمون بدون شبکه)   |   --models ecenc,ecenm,cfsc,cfsm
آزمایشی: ساختار فایل‌ها حدس‌زده/نیمه‌تأییدشده است؛ هر خطا فقط همان مدل را کنار می‌گذارد و در لاگ نوشته می‌شود."""
import argparse, json, math, os, re, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import numpy as np
import nwp_maps as N, styles, lr_maps as L

UTC = timezone.utc
log = N.log
CROP = (16.0, 69.0, 8.0, 46.0)            # lon0, lon1, lat0, lat1 (کمی بزرگ‌تر از کادر خاورمیانه)
EC_BUCKET = 'ecmwf-forecasts'; CFS_BUCKET = 'noaa-cfs-pds'
MODELS = {
    'ecenc': dict(label='ECMWF ENS — کنترل', name='ECMWF-ENS-CTRL', res='0.25°', cyc='00/12', prov='ECMWF Open Data (CC-BY-4.0)', src='ec', mean=False, days=15),
    'ecenm': dict(label='ECMWF ENS — میانگین اعضا', name='ECMWF-ENS-MEAN', res='0.25°', cyc='00/12', prov='ECMWF Open Data (CC-BY-4.0)', src='ec', mean=True, days=15),
    'cfsc':  dict(label='CFS — کنترل (عضو ۱ از ۴ عضو هر اجرا)', name='CFS-CTRL', res='~0.5°', cyc='00/06/12/18', prov='NOAA CFSv2', src='cfs', mean=False, days=45),
    'cfsm':  dict(label='CFS — میانگین ۴ عضو (هموارتر؛ برای بازهٔ بلند مطمئن‌تر)', name='CFS-MEAN', res='~0.5°', cyc='00/06/12/18', prov='NOAA CFSv2', src='cfs', mean=True, days=45),
}
PARAMS = {  # id: (فارسی, واحد, دسته, ترتیب, مقیاس رنگ, خط‌های روی نقشه)
    'p24':   ('بارش ۲۴ ساعته', 'mm', 'pr', 10, 'pr_h24', 0),
    'ptot':  ('بارش تجمعی کل (از ابتدای اجرا)', 'mm', 'pr', 11, 'pr_acc', 0),
    't2m':   ('دمای ۲ متری (میانگین ۲۴ ساعته)', '°C', 'tp', 20, 'temp', 0),
    'z500a': ('ارتفاع ژئوپتانسیل ۵۰۰ هکتوپاسکال و انومالی (دکامتر)', 'dm', 'ul', 30, 'z500a', 1),
}
LOCK = threading.Lock(); DLOCK = threading.Lock()

# ------------------------------------------------------------------ GRIB
def decode(msg):
    """یک پیام GRIB → (مقادیر[lat,lon]، lon، lat) بریده‌شده به CROP. شبکهٔ منظم یا گاوسی منظم."""
    import eccodes as E
    with DLOCK:
        g = E.codes_new_from_message(msg)
        try:
            ni, nj = E.codes_get(g, 'Ni'), E.codes_get(g, 'Nj')
            v = E.codes_get_values(g).reshape(nj, ni).astype(np.float32)
            la = E.codes_get_array(g, 'latitudes').reshape(nj, ni)[:, 0]; lo = E.codes_get_array(g, 'longitudes').reshape(nj, ni)[0]
            miss = E.codes_get(g, 'missingValue') if E.codes_is_defined(g, 'missingValue') else 9999
        finally:
            E.codes_release(g)
    v[v == miss] = np.nan; lo = np.where(lo < 0, lo + 360, lo)
    return crop(v, lo, la)

def crop(v, lo, la):
    o = np.argsort(lo); lo, v = lo[o], v[:, o]
    if la[0] > la[-1]: la, v = la[::-1], v[::-1]
    ix = np.nonzero((lo >= CROP[0]) & (lo <= CROP[1]))[0]; iy = np.nonzero((la >= CROP[2]) & (la <= CROP[3]))[0]
    if len(ix) < 4 or len(iy) < 4: raise RuntimeError('شبکه با کادر خاورمیانه نمی‌خواند')
    return v[np.ix_(iy, ix)], lo[ix], la[iy]

def getb(fs, path, start=None, end=None, tries=4):
    for k in range(tries):
        try: return fs.cat_file(path, start=start, end=end)
        except FileNotFoundError: raise
        except Exception as e:
            if k == tries - 1: raise
            time.sleep(2 * (k + 1))

def S3():
    import s3fs
    return s3fs.S3FileSystem(anon=True)

# ------------------------------------------------------------------ ECMWF ENS
def ec_pick_run(fs):
    now = datetime.now(UTC)
    for dd in (0, 1, 2):
        d = now - timedelta(days=dd)
        for hh in (12, 0):
            base = f'{EC_BUCKET}/{d:%Y%m%d}/{hh:02d}z/ifs/0p25/enfo/{d:%Y%m%d}{hh:02d}0000'
            try:
                if fs.exists(f'{base}-360h-enfo-ef.index') and fs.exists(f'{base}-360h-enfo-ef.grib2'):
                    return datetime(d.year, d.month, d.day, hh, tzinfo=UTC), base
            except Exception as e: log(f'  … بررسی {base}: {e}')
    return None, None

def ec_collect(fs, run, base, days, mean):
    """خروجی: dict var→{step: (arr, lon, lat)}  (برای mean: میانگین ۵۱ عضو؛ وگرنه کنترل)"""
    steps = list(range(6, 24 * days + 1, 6))
    need = {}                                          # step → [(param, level)]
    for s in steps:
        need[s] = [('2t', None)] + ([('tp', None), ('gh', '500')] if s % 24 == 0 else [])
    acc = {}; tasks = []; first = [True]
    def idx(step, suf='ef'):
        txt = getb(fs, f'{base}-{step}h-enfo-{suf}.index').decode()
        ent = [json.loads(l) for l in txt.splitlines() if l.strip()]
        for e in ent: e['_f'] = f'{base}-{step}h-enfo-{suf}.grib2'
        if first[0] and suf == 'ef':
            first[0] = False; from collections import Counter
            log(f'  نمونهٔ index ECMWF: {json.dumps(ent[0])[:240]}')
            log(f'  نوع/شمارهٔ اعضا در index: ' + str(dict(Counter((e.get('type'), 'num' if e.get('number') not in (None, '0', 0) else str(e.get('number'))) for e in ent))))
            try: log('  فایل‌های گام ۶ در پوشه: ' + ' | '.join(sorted(x.rsplit('/', 1)[1] for x in fs.ls(base.rsplit('/', 1)[0]) if '-6h-' in x and 'enfo' in x)))
            except Exception as ex_: log(f'  (فهرست پوشه ممکن نشد: {ex_})')
        return ent
    cf_miss = [0]
    def job(step, e, var):
        b = getb(fs, e['_f'], int(e['_offset']), int(e['_offset']) + int(e['_length']))
        a, lo, la = decode(b)
        with LOCK:
            d = acc.setdefault(var, {}).setdefault(step, dict(sum=np.zeros_like(a, np.float64), n=0, lo=lo, la=la))
            d['sum'] += np.nan_to_num(a, nan=0.0); d['n'] += 1
    t0 = time.time(); errs = [0]
    with ThreadPoolExecutor(16) as ex:
        futs = []
        for s in steps:
            try: ent = idx(s)
            except Exception as e: log(f'  ✗ index گام {s}: {e}'); continue
            if not mean and not any(e.get('type') == 'cf' for e in ent):      # کنترل در فایل ef نیست؛ فایل enfo-cf را امتحان کن
                try: ent = ent + idx(s, 'cf')
                except Exception as e:
                    if not cf_miss[0]: cf_miss[0] = 1; log(f'  ✗ فایل کنترل enfo-cf برای گام {s} پیدا نشد ({type(e).__name__}: {e})')
            for p, lev in need[s]:
                for e in ent:
                    if e.get('param') != p or (lev and str(e.get('levelist')) != lev): continue
                    ctrl = e.get('type') == 'cf' or (e.get('type') == 'pf' and str(e.get('number')) in ('0', '00'))
                    if not (mean or ctrl): continue
                    if mean and e.get('type') not in ('cf', 'pf'): continue
                    futs.append(ex.submit(job, s, e, {'2t': 't2', 'tp': 'tp', 'gh': 'z5'}[p]))
        log(f'  ECMWF: {len(futs)} پیام برای خواندن')
        for f in futs:
            try: f.result()
            except Exception as e:
                errs[0] += 1
                if errs[0] <= 5: log(f'  ✗ پیام: {type(e).__name__}: {e}')
    log(f'  ECMWF خوانده شد ({time.time() - t0:.0f}s؛ {errs[0]} خطا)')
    out = {}
    for var, m in acc.items():
        out[var] = {s: ((d['sum'] / max(d['n'], 1)).astype(np.float32), d['lo'], d['la']) for s, d in m.items() if d['n'] >= (1 if not mean else 10)}
    return out

def ec_products(raw, days):
    """→ {k: dict(p24, t2m, z5)} برای روز k = ۱..days"""
    P = {}
    for k in range(1, days + 1):
        o = {}
        tp, t2, z5 = raw.get('tp', {}), raw.get('t2', {}), raw.get('z5', {})
        if 24 * k in tp and (24 * (k - 1) in tp or k == 1):
            a, lo, la = tp[24 * k]; b = tp[24 * (k - 1)][0] if k > 1 else 0.0
            o['p24'] = (np.maximum(a - b, 0) * 1000.0, lo, la)                 # m → mm
            o['ptot'] = (np.maximum(a, 0) * 1000.0, lo, la)                    # تجمعی از ابتدای اجرا
        ss = [24 * (k - 1) + h for h in (6, 12, 18, 24)]
        if all(s in t2 for s in ss):
            o['t2m'] = (np.mean([t2[s][0] for s in ss], axis=0) - 273.15, t2[ss[0]][1], t2[ss[0]][2])
        if 24 * k in z5: o['z5'] = z5[24 * k]
        if o: P[k] = o
    return P

# ------------------------------------------------------------------ CFS
def cfs_pick_run(fs):
    """جدیدترین چرخهٔ کامل CFS (۴ بار در روز: 00/06/12/18Z)."""
    now = datetime.now(UTC)
    for dd in range(0, 4):
        d = now - timedelta(days=dd)
        for hh in (18, 12, 6, 0):
            r = datetime(d.year, d.month, d.day, hh, tzinfo=UTC)
            if r > now: continue
            day = f'{r:%Y%m%d}'; last = r + timedelta(days=44)
            try:
                if fs.exists(f'{CFS_BUCKET}/cfs.{day}/{hh:02d}/6hrly_grib_02/flxf{last:%Y%m%d%H}.02.{day}{hh:02d}.grb2'): return r
            except Exception as e: log(f'  … بررسی CFS {day} {hh:02d}Z: {e}')
    return None

def cfs_inv(fs, path):
    txt = getb(fs, path + '.idx').decode(); L_ = [l.split(':') for l in txt.splitlines() if l.strip()]
    offs = [int(x[1]) for x in L_]
    return [dict(var=x[3], lev=x[4], ft=x[5] if len(x) > 5 else '', off=offs[i], end=(offs[i + 1] if i + 1 < len(L_) else None)) for i, x in enumerate(L_)]

def cfs_window(ft, B):
    m = re.search(r'(\d+)-(\d+)\s*hour', ft)
    if m: return int(m.group(1)), int(m.group(2))
    m = re.search(r'(\d+)\s*hour\s*(ave|acc)', ft)
    return (B - int(m.group(1)), B) if m else (0, B)

def cfs_member(fs, run, mem, days):
    """یک عضو CFS: dict var→{step: (arr, lo, la)}؛ بارش به‌صورت تجمعی (mm) و دما (K) هر ۶ ساعت، HGT500 فقط ۰۰Z."""
    day = f'{run:%Y%m%d}'; hh = f'{run:%H}'; base = f'{CFS_BUCKET}/cfs.{day}/{hh}/6hrly_grib_{mem}'
    steps = list(range(6, 24 * days + 1, 6)); got = {}
    def one(step):
        v = run + timedelta(hours=step); out = {}
        p = f'{base}/flxf{v:%Y%m%d%H}.{mem}.{day}{hh}.grb2'; inv = cfs_inv(fs, p); r = {}
        for e in inv:
            if e['var'] == 'PRATE' and e['lev'] == 'surface' and 'prate' not in r: r['prate'] = e
            elif e['var'] == 'TMP' and e['lev'].startswith('2 m') and 't2' not in r: r['t2'] = e
        for key, e in r.items():
            a, lo, la = decode(getb(fs, p, e['off'], e['end']))
            out[key] = (a, lo, la, cfs_window(e['ft'], step) if key == 'prate' else None)
            if key == 'prate' and step in (6, 12, 18, 24, 30, 48): log(f"  [تشخیص] عضو {mem} گام {step}: ft='{e['ft']}' → پنجره {cfs_window(e['ft'], step)}")
        if step % 24 == 0:
            p2 = f'{base}/pgbf{v:%Y%m%d%H}.{mem}.{day}{hh}.grb2'
            try:
                for e in cfs_inv(fs, p2):
                    if e['var'] == 'HGT' and e['lev'].strip() == '500 mb':
                        a, lo, la = decode(getb(fs, p2, e['off'], e['end'])); out['z5'] = (a, lo, la, None); break
            except FileNotFoundError: pass
        return step, out
    with ThreadPoolExecutor(6) as ex:
        futs = [ex.submit(one, s) for s in steps]
        for f in futs:
            try: s, o = f.result(); got[s] = o
            except Exception as e:
                if len(got) < 3: log(f'  ✗ CFS عضو {mem}: {type(e).__name__}: {e}')
    res = {'tp': {}, 't2': {}, 'z5': {}}; cum = {0: 0.0}
    for s in sorted(got):
        o = got[s]
        if 'prate' in o:
            a, lo, la, (A, B) = o['prate']; c0 = cum.get(A)
            if c0 is not None:
                cum[B] = c0 + np.nan_to_num(a, nan=0.0) * (B - A) * 3600.0
                if B % 24 == 0: res['tp'][B] = (cum[B], lo, la)
        if 't2' in o: res['t2'][s] = o['t2'][:3]
        if 'z5' in o: res['z5'][s] = o['z5'][:3]
    log(f'  CFS عضو {mem}: {len(got)}/{len(steps)} گام، {len(res["tp"])} روز بارش، {len(res["t2"])} دما، {len(res["z5"])} z500')
    return res

def cfs_collect(fs, run, days, mean):
    mems = ['01', '02', '03', '04'] if mean else ['01']
    with ThreadPoolExecutor(len(mems)) as ex: R = list(ex.map(lambda m: cfs_member(fs, run, m, days), mems))
    out = {}
    for var in ('tp', 't2', 'z5'):
        out[var] = {}
        for s in set().union(*[r[var].keys() for r in R]):
            xs = [r[var][s] for r in R if s in r[var]]
            if len(xs) == len(mems) or (not mean and xs): out[var][s] = (np.mean([x[0] for x in xs], axis=0).astype(np.float32), xs[0][1], xs[0][2])
    return out

def cfs_products(raw, days):
    P = {}
    for k in range(1, days + 1):
        o = {}; tp, t2, z5 = raw['tp'], raw['t2'], raw['z5']
        if 24 * k in tp: o['ptot'] = (np.maximum(tp[24 * k][0], 0), tp[24 * k][1], tp[24 * k][2])
        if 24 * k in tp and (k == 1 or 24 * (k - 1) in tp): o['p24'] = (np.maximum(tp[24 * k][0] - (tp[24 * (k - 1)][0] if k > 1 else 0.0), 0), tp[24 * k][1], tp[24 * k][2])
        ss = [24 * (k - 1) + h for h in (6, 12, 18, 24)]
        if all(s in t2 for s in ss): o['t2m'] = (np.mean([t2[s][0] for s in ss], axis=0) - 273.15, t2[ss[0]][1], t2[ss[0]][2])
        if 24 * k in z5: o['z5'] = z5[24 * k]
        if o: P[k] = o
    return P


def diag_box(prods, tag):
    """r66 تشخیص: میانگین/بیشینهٔ بارش روی ایران (۴۴–۶۳°E، ۲۵–۴۰°N) برای چند روز؛ مقادیر نامعقول (مثلاً بیش از ~۳۰۰ میلی‌متر میانگین در ۴۵ روز) یعنی اشکال در انباشت/پنجرهٔ زمانی."""
    try:
        for k in (1, 5, 15, 30, 45):
            o = prods.get(k, {})
            for key in ('p24', 'ptot'):
                if key not in o: continue
                a, lo, la = o[key]; lo = np.asarray(lo); la = np.asarray(la)
                m = ((la >= 25) & (la <= 40))[:, None] & ((lo >= 44) & (lo <= 63))[None, :]
                v = np.asarray(a)[m]; v = v[np.isfinite(v)]
                if v.size: log(f"  [تشخیص] {tag} روز {k} {key}: میانگین ایران {v.mean():.1f} mm، بیشینه {v.max():.0f} mm")
    except Exception as e: log(f'  [تشخیص] خطا: {e}')

# ------------------------------------------------------------------ ساخت نقشه
class G:  # شبکهٔ کاشی برای اقلیم Z500
    lon = L.LON2; lat = L.LAT2

def make_model(up, mkey, run, prods, a):
    M = MODELS[mkey]; rid = f'{run:%Y%m%d%H}'
    r = up.call('begin', js={'model': mkey, 'run': rid, 'name': M['name'], 'label': M['label'],
                             'info': dict(tclass='ens', res=M['res'], cyc=M['cyc'], prov=M['prov']),
                             'cats': [dict(id=i, fa=f, o=o) for i, f, o in N.CATS],
                             'scales': {k: dict(c=styles.SC[k]['colors'], e=[None if abs(x) == math.inf else x for x in styles.SC[k]['edges']], lo=styles.SC[k]['edges'][0] == -math.inf, hi=styles.SC[k]['edges'][-1] == math.inf) for k in {v[4] for v in PARAMS.values()}},
                             'params': {pid: dict(fa=v[0], unit=v[1], cat=v[2], o=v[3], sc=v[4], mu=v[1], alt='', me=1, ln=v[5]) for pid, v in PARAMS.items()}})
    have = set(r.get('have', [])); made = 0
    for k, o in sorted(prods.items()):
        vt = run + timedelta(hours=24 * k); v = f'{vt:%Y%m%d%H}'; lead = 24 * k
        meta = lambda pid: dict(r='me', m=mkey, p=pid, s=lead, v=v)
        for pid, key in (('p24', 'p24'), ('ptot', 'ptot'), ('t2m', 't2m')):
            fn = f'me/{pid}_{v}.webp'
            if key not in o or fn in have: continue
            f = L.regrid(o[key][0], o[key][1], o[key][2])
            if not np.isfinite(f).any(): continue
            dat, _ = N.render_me(None, f, PARAMS[pid][4]); up.put(mkey, rid, fn, dat, meta(pid)); made += 1
        fn = f'me/z500a_{v}.webp'
        if 'z5' in o and fn not in have:
            C = N.z500_clim_at(G, vt)
            if C is None: continue
            Z = L.regrid(o['z5'][0], o['z5'][1], o['z5'][2])
            dat, lines = N.render_me(None, (Z - C) / 10, 'z500a', cont=Z / 10, cont_lvls=np.arange(480, 620, 4), bold=580)
            up.put(mkey, rid, fn, dat, meta('z500a')); made += 1
            if lines: up.put(mkey, rid, f'me/z500aL_{v}.webp', lines, meta('z500aL'))
    up.wait(); up.call('end', js={'model': mkey, 'run': rid}); log(f'✓ {mkey} {rid}: {made} نقشهٔ تازه')
    return made

def mock_prods(days, seed):
    rng = np.random.default_rng(seed); la = np.arange(CROP[2], CROP[3] + 0.1, 0.25); lo = np.arange(CROP[0], CROP[1] + 0.1, 0.25)
    X, Y = np.meshgrid(lo, la); P = {}; cum = 0
    for k in range(1, days + 1):
        base = np.sin(X / 6 + k * 0.7) * np.cos(Y / 5 - k * 0.4)
        d24 = np.maximum(base * 12 + rng.normal(0, 1, X.shape), 0).astype(np.float32); cum = cum + d24
        P[k] = dict(p24=(d24, lo, la), ptot=(cum.astype(np.float32), lo, la), t2m=((22 + 14 * np.cos(np.radians(Y - 25) * 2) + base * 3).astype(np.float32), lo, la),
                    z5=((5800 + (Y - 30) * -22 + base * 60).astype(np.float32), lo, la))
    return P

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--host'); ap.add_argument('--key', default=''); ap.add_argument('--out'); ap.add_argument('--models', default=','.join(MODELS)); ap.add_argument('--mock', action='store_true')
    a = ap.parse_args()
    if not a.host and not a.out: sys.exit('--host یا --out لازم است')
    up = N.Uploader(a.host, a.key, a.out); tot = 0; fs = None
    if a.mock:
        N.z500_clim_at = lambda R, d: (np.float32(5750) + (R.lat - 30) * -20).astype(np.float32)
    else: fs = S3()
    srcs = {}
    for mk in [m for m in a.models.split(',') if m in MODELS]:
        M = MODELS[mk]
        try:
            if a.mock:
                run = datetime(2026, 10, 15, 0, tzinfo=UTC); prods = mock_prods(M['days'], hash(mk) % 99)
            elif M['src'] == 'ec':
                if 'ec' not in srcs: srcs['ec'] = ec_pick_run(fs)
                run, base = srcs['ec']
                if not run: log(f'✗ {mk}: اجرای کامل ۱۵ روزه در ecmwf-forecasts نیست'); continue
                log(f'▶ {mk}: اجرای {run:%Y-%m-%d %H}Z'); prods = ec_products(ec_collect(fs, run, base, M['days'], M['mean']), M['days'])
            else:
                if 'cfs' not in srcs: srcs['cfs'] = cfs_pick_run(fs)
                run = srcs['cfs']
                if not run: log(f'✗ {mk}: اجرای کامل ۴۵ روزهٔ CFS پیدا نشد'); continue
                log(f'▶ {mk}: اجرای {run:%Y-%m-%d %H}Z'); prods = cfs_products(cfs_collect(fs, run, M['days'], M['mean']), M['days']); diag_box(prods, mk)
            if not prods: log(f'✗ {mk}: هیچ روزی ساخته نشد'); continue
            tot += make_model(up, mk, run, prods, a)
        except SystemExit: raise
        except Exception as e:
            import traceback; traceback.print_exc(); log(f'✗ {mk}: {type(e).__name__}: {e}')
    log(f'پایان: {tot} نقشه'); sys.exit(0)

if __name__ == '__main__': main()

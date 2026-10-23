#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""نمودار فازی MJO (OMI) + پیش‌بینی آماری ۳۰ روزه به روش «آنالوگ» — برای بخش شاخص‌های سایت.
داده: NOAA PSL  https://psl.noaa.gov/mjo/mjoindex/omi.1x.txt  (OMI؛ ۱۹۷۹ تا امروز؛ ستون‌ها سال ماه روز ساعت PC1 PC2 دامنه).
نمودار استاندارد: x = RMM1 = OMI PC2 ، y = RMM2 = −OMI PC1  (همان قرارداد mjo_index.py؛ فازها ۱–۸ خلاف جهت عقربه).
پیش‌بینی (آماری، نه مدل دینامیکی): برای وضعیت امروز و دو عکس ۵ و ۱۰ روز قبل، K روز مشابه در همان فصل (±۶۰ روز از روز سال) از تاریخچه پیدا می‌شود
  (فاصلهٔ اقلیدسی روی ۳×(x,y)، جداافتادگی ≥۱۰ روز بین آنالوگ‌ها)؛ مسیر ۳۰ روز بعد هر آنالوگ یک «عضو» است؛ میانگین اعضا = پیش‌بینی.
  این روش مهارت ~۱۰–۱۵ روزهٔ مدل‌های آماری ساده را دارد و جایگزین پیش‌بینی ECMWF/GEFS/BoM نیست.
خروجی: <out>/mjo_fc.json (سری) و mjo_fc_<per>.png؛ با --host/--key به nwp_upload.php?a=idxput آپلود می‌شود (کنار شاخص‌های دیگر).
اجرا: python mjo_fc.py --host H --key K   |   python mjo_fc.py --mock --out out"""
import argparse, io, json, math, os, sys, datetime as dt, urllib.request
import numpy as np
URL = 'https://psl.noaa.gov/mjo/mjoindex/omi.1x.txt'
URL_BOM = 'https://www.bom.gov.au/climate/mjo/graphics/rmm.74toRealtime.txt'   # RMM (BoM) — جایگزین وقتی OMI قدیمی است
UA = {'User-Agent': 'MetStat/1.0 (wtafkik.ir)'}
LEADS = 30; K = 30; SRC = ['NOAA PSL OMI']
def log(*a): print(*a, flush=True)
def parse(txt):
    D = {}
    for ln in txt.splitlines():
        t = ln.replace(',', ' ').split()
        if len(t) < 6: continue
        try: y, m, d = int(float(t[0])), int(float(t[1])), int(float(t[2])); p1, p2, a = float(t[-3]), float(t[-2]), float(t[-1])
        except ValueError: continue
        if not (1900 < y < 2100 and 1 <= m <= 12 and 1 <= d <= 31) or max(abs(p1), abs(p2), abs(a)) >= 99: continue
        D[dt.date(y, m, d)] = (p2, -p1)       # (RMM1, RMM2)
    return D
def parse_bom(txt):
    """BoM RMM: ستون‌ها سال ماه روز RMM1 RMM2 فاز دامنه [منبع]؛ مقدار گمشده 1.E36 یا 999."""
    D = {}
    for ln in txt.splitlines():
        t = ln.replace(',', ' ').split()
        if len(t) < 5: continue
        try: y, m, d = int(float(t[0])), int(float(t[1])), int(float(t[2])); x, yy = float(t[3]), float(t[4])
        except ValueError: continue
        if not (1900 < y < 2100 and 1 <= m <= 12 and 1 <= d <= 31) or max(abs(x), abs(yy)) >= 99: continue
        D[dt.date(y, m, d)] = (x, yy)
    return D
def fill(D):
    ds = sorted(D); d0, d1 = ds[0], ds[-1]; n = (d1 - d0).days + 1
    T = [d0 + dt.timedelta(days=i) for i in range(n)]; X = np.full(n, np.nan); Y = np.full(n, np.nan)
    for d, (x, y) in D.items(): X[(d - d0).days] = x; Y[(d - d0).days] = y
    return T, X, Y
def phase(x, y):
    if not (math.isfinite(x) and math.isfinite(y)): return 0
    ang = math.degrees(math.atan2(y, x)) % 360                      # فاز ۵ = (−1,0) تا ... طبق Wheeler–Hendon: فاز۱ ۱۸۰–۲۲۵°
    return int(((ang - 180) % 360) // 45) + 1
def analogs(X, Y, T, K=K, win=60, sep=10):
    n = len(X); i0 = n - 1
    while i0 > 10 and not (math.isfinite(X[i0]) and math.isfinite(Y[i0])): i0 -= 1      # آخرین روز معتبر
    cur = np.array([X[i0], Y[i0], X[i0 - 5], Y[i0 - 5], X[i0 - 10], Y[i0 - 10]])
    doy0 = T[i0].timetuple().tm_yday; cand = []
    for j in range(10, n - LEADS - 1):
        if abs(((T[j].timetuple().tm_yday - doy0 + 183) % 365) - 183) > win: continue
        v = np.array([X[j], Y[j], X[j - 5], Y[j - 5], X[j - 10], Y[j - 10]])
        fut = np.concatenate([X[j:j + LEADS + 1], Y[j:j + LEADS + 1]])
        if np.isnan(v).any() or np.isnan(fut).any(): continue
        cand.append((float(np.sqrt(((v - cur) ** 2).sum())), j))
    cand.sort(); pick = []
    for dist, j in cand:
        if all(abs(j - q) >= sep for _, q in pick): pick.append((dist, j))
        if len(pick) >= K: break
    mem = [(X[j:j + LEADS + 1].copy(), Y[j:j + LEADS + 1].copy()) for _, j in pick]
    return i0, mem, [d for d, _ in pick]
def build(D, now):
    T, X, Y = fill(D); i0, mem, dist = analogs(X, Y, T); last = T[i0]
    mx = np.mean([m[0] for m in mem], 0); my = np.mean([m[1] for m in mem], 0)
    # آنالوگ‌ها از فضای مطلق‌اند؛ برای پیوستگی، ۵ روز اول به وضعیت واقعی امروز می‌چسبد
    w = np.clip(np.arange(LEADS + 1) / 5.0, 0, 1); mx = (1 - w) * X[i0] + w * mx; my = (1 - w) * Y[i0] + w * my
    n_obs = 120; s = max(0, i0 - n_obs + 1)
    r = lambda a: [None if not math.isfinite(v) else round(float(v), 3) for v in a]
    ser = dict(kind='mjo', obs=dict(t=[T[k].isoformat() for k in range(s, i0 + 1)], x=r(X[s:i0 + 1]), y=r(Y[s:i0 + 1])),
               fc=dict(init=last.isoformat(), lead=list(range(LEADS + 1)), mean=dict(x=r(mx), y=r(my)), mem=[dict(x=r(a), y=r(b)) for a, b in mem], n=len(mem), method='analog'))
    amp = float(math.hypot(X[i0], Y[i0])); return ser, last, amp, phase(X[i0], Y[i0])
def render(ser, days, meta):
    import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(7.4, 7.4), dpi=130); th = np.linspace(0, 2 * np.pi, 200)
    ax.plot(np.cos(th), np.sin(th), color='#555', lw=1.2); R = 4
    for k in range(8):
        a = math.radians(180 + 45 * k); ax.plot([math.cos(a) * 1, math.cos(a) * R], [math.sin(a) * 1, math.sin(a) * R], color='#bbb', lw=.8)
        b = math.radians(180 + 45 * k + 22.5); ax.text(math.cos(b) * 3.45, math.sin(b) * 3.45, f'{k + 1}', ha='center', va='center', fontsize=15, color='#888', weight='bold')
    ob = ser['obs']; xs = [v for v in ob['x'][-days:]]; ys = [v for v in ob['y'][-days:]]
    ax.plot([v if v is not None else np.nan for v in xs], [v if v is not None else np.nan for v in ys], '-', color='#0f172a', lw=2.2, zorder=4)
    for i in range(0, len(xs), 5):
        if xs[i] is not None: ax.plot(xs[i], ys[i], 'o', color='#0f172a', ms=4.5, zorder=5)
    fc = ser['fc']
    for m in fc['mem']: ax.plot(m['x'], m['y'], '-', color='#6366f1', lw=.8, alpha=.28, zorder=2)
    ax.plot(fc['mean']['x'], fc['mean']['y'], '-', color='#7c3aed', lw=3, zorder=6)
    for l in range(0, LEADS + 1, 5): ax.plot(fc['mean']['x'][l], fc['mean']['y'][l], 'o', color='#7c3aed', ms=5.5, zorder=7); ax.annotate(f'+{l}', (fc['mean']['x'][l], fc['mean']['y'][l]), textcoords='offset points', xytext=(5, 5), fontsize=9, color='#5b21b6')
    ax.set_xlim(-R, R); ax.set_ylim(-R, R); ax.set_aspect('equal'); ax.set_xlabel('RMM1 (OMI PC2)'); ax.set_ylabel('RMM2 (−OMI PC1)')
    ax.text(-R + .15, -R + .2, 'Indian Ocean ← → Maritime Continent / W. Pacific', fontsize=7.5, color='#888')
    ax.set_title(f'MJO phase diagram · last {days} d (black) + analog forecast {LEADS} d (purple: mean, thin: members)', fontsize=10.5)
    fig.text(.01, .012, f'MetStat · {SRC[0]} · statistical analog forecast (not a dynamical model) · updated {meta["upd"]}', fontsize=8, color='#666')
    b = io.BytesIO(); fig.savefig(b, format='png'); plt.close(fig); return b.getvalue()
def mock():
    rng = np.random.default_rng(3); n = 365 * 30; t = np.arange(n); ph = 2 * np.pi * t / 48.0 + np.cumsum(rng.normal(0, .08, n)); a = 1.1 + .9 * np.sin(2 * np.pi * t / 700) + rng.normal(0, .15, n)
    d0 = dt.date(1995, 1, 1); return {d0 + dt.timedelta(days=int(i)): (float(a[i] * np.cos(ph[i])), float(a[i] * np.sin(ph[i]))) for i in range(n)}
def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--host'); ap.add_argument('--key'); ap.add_argument('--out'); ap.add_argument('--mock', action='store_true'); a = ap.parse_args()
    now = dt.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S')
    if a.mock: D = mock()
    else:
        req = urllib.request.Request(URL, headers=UA)
        with urllib.request.urlopen(req, timeout=90) as r: D = parse(r.read().decode('utf-8', 'replace'))
        age = (dt.date.today() - max(D)).days if D else 9999
        log(f'OMI: {len(D)} روز، آخرین روز {max(D) if D else "—"} (سن {age} روز)')
        if age > 10:      # فایل OMI قدیمی است؛ RMM بوم (استرالیا) را امتحان کن
            try:
                req = urllib.request.Request(URL_BOM, headers=UA)
                with urllib.request.urlopen(req, timeout=90) as r: txt = r.read().decode('utf-8', 'replace')
                B = parse_bom(txt); ab = (dt.date.today() - max(B)).days if B else 9999
                log(f'BoM RMM: {len(B)} روز، آخرین روز {max(B) if B else "—"} (سن {ab} روز)')
                if B and ab < age and len(B) >= 3000: D = B; SRC[0] = 'BoM RMM'
                elif not B: log('  شروع فایل BoM:', txt[:300].replace('\n', ' | '))
            except Exception as e: log(f'✗ BoM در دسترس نیست: {e}')
    if len(D) < 3000: sys.exit(f'✗ دادهٔ OMI ناکافی ({len(D)} روز)')
    ser, last, amp, ph = build(D, now)
    meta = dict(fa='MJO — نمودار فازی و پیش‌بینی آماری (OMI)', en='MJO phase diagram · OMI + statistical analog forecast', grp='MJO', src=SRC[0] + ' + MetStat analog forecast', last=last.isoformat(), upd=now, unit='', kind='mjo', val=round(amp, 2),
                note='پیش‌بینی ۳۰ روزهٔ آماری (آنالوگ) است؛ جایگزین پیش‌بینی دینامیکی ECMWF/GEFS نیست', since=f'فاز {ph}')
    b = json.dumps(ser, ensure_ascii=False, separators=(',', ':')).encode()
    if a.out: os.makedirs(a.out, exist_ok=True); open(os.path.join(a.out, 'mjo_fc.json'), 'wb').write(b)
    if a.host:
        import requests; import indices as IX
    first = True
    for per, days in (('d90', 90), ('d30', 30), ('d60', 60), ('d120', 120)):
        png = render(ser, days, meta)
        if a.out: open(os.path.join(a.out, f'mjo_fc_{per}.png'), 'wb').write(png)
        if a.host: IX.post(a, 'mjo_fc', per, png, dict(meta, perfa=f'{IX.fa(days)} روز اخیر + پیش‌بینی ۳۰ روزه'), requests, b if first else None); first = False
    if a.host: requests.post(f'{a.host.rstrip("/")}/nwp_upload.php?a=idxend&key={requests.utils.quote(a.key)}', timeout=60)
    log(f'✓ MJO: آخرین روز {last}، دامنه {amp:.2f}، فاز {ph}، اعضا {ser["fc"]["n"]}')
if __name__ == '__main__': main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""شاخص MJO روزانه (OMI از NOAA PSL) برای صفحهٔ «شاخص‌های اقلیمی» سایت (r56).
خروجی روی هاست (همان مسیر indices.py: idxput): شناسهٔ «mjo»، نوع kind='mjo' → نمودار فضای فاز (RMM1/RMM2) با دنبالهٔ روزانهٔ ۱۲۰ روز اخیر + تصویر PNG جایگزین.
RMM1 = OMI PC2 و RMM2 = −OMI PC1 (همان قرارداد mjo_index.py)، فاز طبق Wheeler–Hendon. دامنهٔ کمتر از ۱ = MJO ضعیف.
پیش‌بینی MJO: هنوز منبع تأییدشده‌ای وصل نیست. اگر فایل JSON پیش‌بینی با قالب زیر در یک آدرس عمومی باشد، با --fc-url خوانده می‌شود:
   {"init":"YYYY-MM-DD","lead":[1,2,...],"mean":[[rmm1,rmm2],...],"mem":[[[rmm1,rmm2],...],...]}   (mjo_gefs → mdl=gfs، mjo_ecmwf → mdl=ecmwf با --fc-id و --fc-mdl)
اجرا:  python mjo_idx.py --host https://wtafkik.ir/online --key KEY   |   --mock --out out"""
import argparse, io, json, math, os, sys, time, datetime as dt, urllib.request
import numpy as np
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
UA = {'User-Agent': 'MetStat/1.0 (wtafkik.ir)'}
URL = 'https://psl.noaa.gov/mjo/mjoindex/omi.1x.txt'
def log(*a): print(*a, flush=True)
def get(u):
    with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=90) as r: return r.read().decode('utf-8', 'replace')
def parse(txt):
    out = {}
    for ln in txt.splitlines():
        t = ln.replace(',', ' ').split()
        if len(t) < 6: continue
        try: y, m, d = int(float(t[0])), int(float(t[1])), int(float(t[2])); p1, p2, a = float(t[-3]), float(t[-2]), float(t[-1])
        except ValueError: continue
        if not (1900 < y < 2100 and 1 <= m <= 12 and 1 <= d <= 31) or max(abs(p1), abs(p2), abs(a)) >= 99: continue
        out[dt.date(y, m, d)] = (p2, -p1, a)                      # (RMM1, RMM2, دامنه)
    return out
def phase(r1, r2): return int(((math.degrees(math.atan2(r2, r1)) % 360 - 180) % 360) // 45) + 1
def mock():
    import random; r = random.Random(2); t0 = dt.date.today() - dt.timedelta(days=3); out = {}
    for i in range(400):
        d = t0 - dt.timedelta(days=399 - i); ang = math.radians(200 + i * 5.5); a = 0.4 + 1.4 * abs(math.sin(i / 17))
        out[d] = (a * math.cos(ang), a * math.sin(ang), a)
    return out
PH = ['1', '2', '3', '4', '5', '6', '7', '8']
def png(days, fc=None):
    fig, ax = plt.subplots(figsize=(6.4, 6.4), dpi=130); L = 4
    ax.set_xlim(-L, L); ax.set_ylim(-L, L); ax.set_aspect('equal'); ax.grid(alpha=.25)
    for i in range(8):
        a0 = math.radians(180 + 45 * i); ax.plot([0, 6 * math.cos(a0)], [0, 6 * math.sin(a0)], color='#cbd5e1', lw=1)
        am = a0 + math.pi / 8; ax.text(3.2 * math.cos(am), 3.2 * math.sin(am), PH[i], ha='center', va='center', fontsize=20, color='#94a3b8', fontweight='bold')
    ax.add_patch(plt.Circle((0, 0), 1, color='#e5e7eb', alpha=.85, ec='#94a3b8'))
    ts = sorted(days)[-60:]; x = [days[t][0] for t in ts]; y = [days[t][1] for t in ts]
    ax.plot(x, y, color='white', lw=5); ax.plot(x, y, color='#0f172a', lw=2.2); ax.plot(x[-1], y[-1], 'o', color='#dc2626', ms=8, mec='white')
    if fc:
        for m in fc.get('mem', []): ax.plot([x[-1]] + [p[0] for p in m], [y[-1]] + [p[1] for p in m], color='#6366f1', lw=.8, alpha=.3)
        mm = fc.get('mean')
        if mm: ax.plot([x[-1]] + [p[0] for p in mm], [y[-1]] + [p[1] for p in mm], color='#7c3aed', lw=3)
    ax.set_xlabel('RMM1'); ax.set_ylabel('RMM2'); ax.set_title(f'MJO (OMI) — {ts[-1]}  amplitude {days[ts[-1]][2]:.2f}', fontsize=11)
    ax.text(.99, .01, 'MetStat · NOAA PSL OMI', transform=ax.transAxes, ha='right', va='bottom', fontsize=7, color='#94a3b8')
    b = io.BytesIO(); fig.savefig(b, format='png', facecolor='white'); plt.close(fig); return b.getvalue()
def ser(days, fc, n=120):
    ts = sorted(days)[-n:]
    S = dict(kind='mjo', obs=dict(t=[t.isoformat() for t in ts], a=[round(days[t][0], 3) for t in ts], b=[round(days[t][1], 3) for t in ts]))
    if fc: S['fc'] = fc
    return json.dumps(S, separators=(',', ':')).encode()
def post(a, iid, per, pngb, meta, requests, serb=None):
    u = f'{a.host.rstrip("/")}/nwp_upload.php?a=idxput&key={requests.utils.quote(a.key)}'
    files = {'png': (f'{iid}_{per}.png', pngb, 'image/png')}
    if serb is not None: files['ser'] = (f'{iid}.json', serb, 'application/json')
    for k in range(4):
        try:
            r = requests.post(u, data=dict(id=iid, per=per, meta=json.dumps(meta)), files=files, timeout=90)
            if r.status_code == 403: sys.exit('✗ کلید آپلود اشتباه است')
            if r.json().get('ok'): return True
            log(f'  ✗ پاسخ هاست {iid}/{per}: {r.text[:120]}')
        except SystemExit: raise
        except Exception as e: log(f'  … {e}'); time.sleep(4 * (k + 1))
    return False
def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--host'); ap.add_argument('--key'); ap.add_argument('--out'); ap.add_argument('--mock', action='store_true')
    ap.add_argument('--fc-url'); ap.add_argument('--fc-id', default='mjo_gefs'); ap.add_argument('--fc-mdl', default='gfs')
    a = ap.parse_args(); import requests
    days = mock() if a.mock else parse(get(URL))
    if not days: sys.exit('✗ داده OMI خوانده نشد')
    last = max(days); age = (dt.date.today() - last).days; r1, r2, amp = days[last]
    log(f'MJO/OMI: {len(days)} روز، آخرین روز {last} (سن {age} روز)، دامنه {amp:.2f}، فاز {phase(r1, r2)}')
    if age > 10: log(f'  ؟ داده {age} روز قدیمی است (منبع به‌روز نشده)')
    now = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d')
    pers = {'d60': '۶۰ روز اخیر', 'd30': '۳۰ روز اخیر', 'd120': '۱۲۰ روز اخیر'}
    prev = days.get(last - dt.timedelta(days=30)); 
    meta = dict(fa='MJO — فضای فاز (OMI)', en='MJO — phase space (OMI)', grp='استوایی', src='NOAA PSL · OMI', last=last.isoformat(), upd=now, unit='', kind='mjo',
                note=f'RMM1/RMM2؛ آخرین فاز {phase(r1, r2)}', val=round(amp, 3), prev=round(prev[2], 3) if prev else None)
    sb = ser(days, None); pb = png(days)
    if a.out: os.makedirs(a.out, exist_ok=True); open(os.path.join(a.out, 'mjo.json'), 'wb').write(sb); open(os.path.join(a.out, 'mjo_d60.png'), 'wb').write(pb)
    ok = True
    if a.host:
        first = True
        for per, fa_ in pers.items(): ok &= post(a, 'mjo', per, pb, dict(meta, perfa=fa_), requests, sb if first else None); first = False
    if a.fc_url:
        try:
            fc = json.loads(get(a.fc_url)); assert fc.get('mean') or fc.get('mem')
            sb2 = ser(days, fc); pb2 = png(days, fc); m2 = dict(meta, fa='MJO — پیش‌بینی', en='MJO — forecast', grp='پیش‌بینی روزانه', kind='mjo', mdl=a.fc_mdl, note='پیش‌بینی اعضای مدل')
            if a.out: open(os.path.join(a.out, a.fc_id + '.json'), 'wb').write(sb2)
            if a.host:
                first = True
                for per, fa_ in pers.items(): ok &= post(a, a.fc_id, per, pb2, dict(m2, perfa=fa_ + ' + پیش‌بینی'), requests, sb2 if first else None); first = False
            log(f'✓ پیش‌بینی MJO ({a.fc_id}) از {a.fc_url}')
        except Exception as e: log(f'✗ پیش‌بینی MJO خوانده نشد: {e}')
    else: log('ℹ پیش‌بینی MJO: --fc-url داده نشده؛ فقط مشاهدهٔ OMI آپلود شد')
    if a.host: requests.post(f'{a.host.rstrip("/")}/nwp_upload.php?a=idxend&key={requests.utils.quote(a.key)}', timeout=60)
    log('✓ MJO پایان' if ok else '✗ بخشی از آپلود ناموفق بود'); sys.exit(0 if ok else 1)
if __name__ == '__main__': main()

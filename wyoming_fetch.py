#!/usr/bin/env python3
"""r130 — سونداژ مشاهده‌ای (رادیوسوند) ایستگاه‌های ایران از دانشگاه وایومینگ.
هر اجرا: برای هر ایستگاه، ۴ نوبت آخر (۰۰ و ۱۲ UTC در ۲ روز اخیر) را می‌گیرد، متن جدول را (بدون HTML) نگه می‌دارد
و همه را با یک POST به nwp_upload.php?a=sndput می‌فرستد. ایستگاه/نوبتِ بدون داده بی‌صدا رد می‌شود.
استفاده:  python wyoming_fetch.py --host https://wtafkik.ir/online --key KEY      (بدون --host فقط در پوشهٔ out می‌نویسد)
"""
import argparse, html, json, re, sys, time, datetime as dt
import requests

STATIONS = [  # WMO id, فارسی, English  (ایستگاه‌هایی که داده نداشته باشند خودکار حذف می‌شوند)
    ('40745', 'مشهد', 'Mashhad'), ('40754', 'تهران', 'Tehran'), ('40706', 'تبریز', 'Tabriz'), ('40766', 'کرمانشاه', 'Kermanshah'),
    ('40800', 'اصفهان', 'Isfahan'), ('40811', 'اهواز', 'Ahvaz'), ('40848', 'شیراز', 'Shiraz'), ('40856', 'زاهدان', 'Zahedan'),
    ('40858', 'بوشهر', 'Bushehr'), ('40875', 'بندرعباس', 'Bandar Abbas'), ('40809', 'بیرجند', 'Birjand'), ('40718', 'ارومیه', 'Urmia'),
]
URL = 'https://weather.uwyo.edu/cgi-bin/sounding'

def table_text(page: str):
    """متن جدول سونداژ را از اولین <pre> بیرون می‌کشد؛ نبود داده → None."""
    m = re.search(r'<pre[^>]*>(.*?)</pre>', page, re.S | re.I)
    if not m: return None
    t = html.unescape(re.sub(r'<[^>]+>', '', m.group(1))).strip('\n')
    if 'PRES' not in t or len(re.findall(r'^\s*\d{3,4}\.\d', t, re.M)) < 8: return None
    return t

URL_NEW = 'https://weather.uwyo.edu/wsgi/sounding'
DIAG = {}   # r138: دلیل شکست هر ایستگاه (برای لاگ)

def _get(s, url, params):
    try:
        r = s.get(url, params=params, timeout=40)
        return r.status_code, r.text
    except requests.RequestException as e:
        return -1, str(e)

def fetch_one(s, stn, when):
    """r138: نشانی جدید دانشگاه وایومینگ (wsgi) با چند منبع، سپس نشانی قدیمی (cgi-bin). دلیل شکست در DIAG ثبت می‌شود."""
    tries = []
    for src in ('UNKNOWN', 'BUFR', 'TEMP'):
        tries.append((URL_NEW, dict(datetime=when.strftime('%Y-%m-%d %H:00:00'), id=stn, src=src, type='TEXT:LIST')))
    for reg in ('naconf', 'mideast'):
        tries.append((URL, dict(region=reg, TYPE='TEXT:LIST', YEAR=when.year, MONTH=when.month, FROM=f'{when.day:02d}{when.hour:02d}', TO=f'{when.day:02d}{when.hour:02d}', STNM=stn)))
    for url, q in tries:
        code, txt = _get(s, url, q)
        if code == 200:
            tx = table_text(txt)
            if tx: return tx
            DIAG.setdefault(stn, f'{url.split("/")[-1]} {q.get("src") or q.get("region")}: 200 بدون جدول — «{re.sub(chr(10)," ",re.sub("<[^>]+>"," ",txt))[:90].strip()}»')
        else:
            DIAG.setdefault(stn, f'{url.split("/")[-1]} {q.get("src") or q.get("region")}: HTTP {code}')
        time.sleep(1.0)
    return None

def run(days=2, only=None):
    now = dt.datetime.now(dt.timezone.utc).replace(minute=0, second=0, microsecond=0)
    times = []
    for d in range(days + 1):
        for h in (12, 0):
            t = (now - dt.timedelta(days=d)).replace(hour=h)
            if t <= now - dt.timedelta(hours=2): times.append(t)
    times = sorted(set(times), reverse=True)[:4]
    s = requests.Session(); s.headers['User-Agent'] = 'MetStat-sounding/1.0 (wtafkik.ir)'
    out = []
    for stn, fa, en in STATIONS:
        if only and stn not in only: continue
        runs = []
        for t in times:
            tx = fetch_one(s, stn, t)
            if tx: runs.append({'t': t.strftime('%Y-%m-%d %HZ'), 'f': f'{stn}_{t:%Y%m%d%H}.txt', 'txt': tx})
            time.sleep(1.0)
        print(f'{stn} {en}: {len(runs)} sounding(s)' + ('' if runs else '  ← ' + DIAG.get(stn, '')))
        if runs: out.append({'id': stn, 'fa': fa, 'en': en, 'runs': runs})
    return {'v': 1, 'generated': now.strftime('%Y-%m-%d %H:%MZ'), 'stations': out}

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--host', default=''); ap.add_argument('--key', default=''); ap.add_argument('--out', default='soundings.json'); ap.add_argument('--only', default='')
    a = ap.parse_args()
    J = run(only=set(filter(None, a.only.split(','))))
    json.dump(J, open(a.out, 'w', encoding='utf8'), ensure_ascii=False)
    if not J['stations']: print('هیچ سونداژی دریافت نشد؛ آپلود انجام نشد'); return 0
    if a.host:
        r = requests.post(a.host.rstrip('/') + '/nwp_upload.php?a=sndput', json=J, headers={'X-Upload-Key': a.key}, timeout=120)
        print('upload:', r.status_code, r.text[:200])
        if r.status_code != 200: return 1
    return 0

if __name__ == '__main__': sys.exit(main())

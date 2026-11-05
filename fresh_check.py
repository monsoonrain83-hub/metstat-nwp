#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MetStat r193 — بررسی تازگی واقعی مدل‌های ماهانه/فصلی/هفتگی/ENS از روی manifest هاست.
«موفق بودن اجرای workflow» به معنای تازه بودن داده نیست (اسکریپت‌ها همیشه با کد 0 خارج می‌شوند).
این اسکریپت فقط نتیجه را چاپ می‌کند:  TRIGGER <workflow.yml> | DEAD <مدل> | ORPHAN <مدل> | OK/INFO
اجرا:  python fresh_check.py --manifest URL_یا_فایل  [--now 2026-11-05T07:00]
"""
import argparse, json, sys, urllib.request
from datetime import datetime, timezone, timedelta

H = 1; D = 24
# workflow → (مدل‌ها, حداکثر سن مجاز بر حسب ساعت). سقف‌ها با چرخهٔ انتشار هر منبع و کران بالای تأخیر عادی تنظیم شده‌اند.
RULES = [
    ('ens.yml',        ['ecenc', 'ecenm', 'cfsc', 'cfsm'], 36 * H),     # ۶ اجرا در روز؛ ران 12Z حدود ۸ ساعت دیرتر کامل می‌شود
    ('ec46.yml',       ['ec46c', 'ec46m'],                 60 * H),     # روزانه
    ('wk.yml',         ['cfswk'],                          48 * H),
    ('wk.yml',         ['ecwk'],                           5 * D),      # EC46 هفته‌ای دو بار (دوشنبه/پنجشنبه) به‌روز می‌شود
    ('wk.yml',         ['iri'],                            45 * D),     # ماهانه
    ('nwp-extra.yml',  ['nmme', 'cfsv2', 'nasa', 'gfdl'],  45 * D),     # NMME ماهانه (حدود روز ۸–۱۰)
]
DEAD_AFTER = 120 * D                                                     # قدیمی‌تر از این = منبع احتمالاً متوقف شده
ORPHAN = ['cfsvtwo', 'cfsvtwos', 'nmmes', 'nasas', 'ecmwfs', 'ecmwfseas', 'ecmwfseass']   # تولیدکننده‌شان در مخزن نیست

def load(src):
    if src.startswith('http'):
        req = urllib.request.Request(src, headers={'User-Agent': 'MetStat-fresh/1.0'})
        return json.load(urllib.request.urlopen(req, timeout=60))
    return json.load(open(src, encoding='utf-8'))

def age_h(run, now):
    try: t = datetime.strptime(str(run)[:10].ljust(10, '0'), '%Y%m%d%H').replace(tzinfo=timezone.utc)
    except Exception: return None
    return (now - t).total_seconds() / 3600

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--manifest', required=True); ap.add_argument('--now')
    a = ap.parse_args()
    now = datetime.fromisoformat(a.now).replace(tzinfo=timezone.utc) if a.now else datetime.now(timezone.utc)
    try: M = load(a.manifest)['models']
    except Exception as e:
        print(f'INFO manifest خوانده نشد ({type(e).__name__}: {e}) — هیچ اجرایی راه‌اندازی نمی‌شود'); return 0
    trig = []
    for wf, keys, lim in RULES:
        for k in keys:
            if k not in M: print(f'INFO {k}: در manifest نیست'); continue
            ah = age_h(M[k].get('run'), now)
            if ah is None: print(f'INFO {k}: تاریخ اجرا نامعتبر'); continue
            if ah > DEAD_AFTER: print(f'DEAD {k} {ah / 24:.0f} روز'); continue
            st = 'STALE' if ah > lim else 'OK'
            print(f'{st} {k} سن={ah / 24:.1f}روز سقف={lim / 24:.1f}روز → {wf}')
            if st == 'STALE' and wf not in trig: trig.append(wf)
    for k in M:                                                       # مدل‌های متوقف‌شده‌ای که هیچ قاعده‌ای ندارند
        if k in ORPHAN: print(f'ORPHAN {k} سن={age_h(M[k].get("run"), now) / 24:.1f}روز')
        elif k not in sum([r[1] for r in RULES], []) and M[k].get('info', {}).get('tclass') != 'daily':
            ah = age_h(M[k].get('run'), now)
            if ah and ah > DEAD_AFTER: print(f'DEAD {k} {ah / 24:.0f} روز')
    for wf in trig: print('TRIGGER', wf)
    return 0

if __name__ == '__main__': sys.exit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MetStat r97 — ساخت روزانهٔ «پیش‌بینی ماهانه و فصلی» روی سرور (یک‌بار در روز، برای همهٔ کاربران).
سایت زندهٔ شما را در Chromium بی‌سر باز می‌کند، همان کد صفحه (67_seasonal_fc.js) پیش‌بینی ۵ ماه را می‌سازد،
نتیجه (بدون نقشهٔ تصویری؛ فقط اعداد) به صورت online/data/sfc/sfc_result_prcp.json و sfc_result_tmean.json روی هاست می‌رود؛
صفحه اگر فایل امروز/دیروز را ببیند، بی‌درنگ نقشه‌ها را نشان می‌دهد و خودش محاسبه نمی‌کند.
اجرا:  python sfc_precompute.py --site https://wtafkik.ir --host $MX_HOST --key $MX_KEY   |   --out dir  (فقط ذخیره، بدون آپلود)"""
import argparse, json, os, sys, urllib.request
from playwright.sync_api import sync_playwright

def put(host, key, name, data):
    req = urllib.request.Request(f"{host.rstrip('/')}/nwp_upload.php?a=sfput&name={name}&key={key}", data=data, method="POST")
    with urllib.request.urlopen(req, timeout=240) as r: return r.status, r.read(200).decode("utf8", "ignore")

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--site", default="https://wtafkik.ir"); ap.add_argument("--host", default=os.environ.get("MX_HOST", "")); ap.add_argument("--key", default=os.environ.get("MX_KEY", "")); ap.add_argument("--out", default="sfc_pre"); ap.add_argument("--pars", default="prcp,tmean")
    a = ap.parse_args(); os.makedirs(a.out, exist_ok=True); ok = 0
    with sync_playwright() as p:
        b = p.chromium.launch()
        for par in a.pars.split(","):
            pg = b.new_page(viewport={"width": 1200, "height": 900}); pg.set_default_timeout(900000)
            pg.goto(a.site.rstrip("/") + "/index.html", wait_until="load"); pg.wait_for_function("typeof sfRunAuto==='function' && typeof SF!=='undefined'")
            pack = pg.evaluate("""async (par)=>{ try{ SF.o.par=par; SF.o.reg=""; SF.noPre=true; SF.out={}; SF.views={}; await sfLoad(); await sfRunAuto();
                const R=window.sfPack(); return R?JSON.stringify(R):"ERR:"+(document.getElementById('sfStatus')?document.getElementById('sfStatus').textContent:"nopack"); }catch(e){ return "ERR:"+e.message; } }""", par)
            pg.close()
            if pack.startswith("ERR") or len(pack) < 1000: print("✗", par, pack[:200]); continue
            fn = f"sfc_result_{par}.json"; open(os.path.join(a.out, fn), "w", encoding="utf8").write(pack); print("✓", fn, len(pack) // 1024, "KB")
            if a.host and a.key:
                st, tx = put(a.host, a.key, fn, pack.encode("utf8")); print("  upload", st, tx[:80]); ok += st == 200
            else: ok += 1
        b.close()
    sys.exit(0 if ok else 1)
main()

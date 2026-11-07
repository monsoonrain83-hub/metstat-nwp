#!/usr/bin/env python3
"""Stage 1: build data/obs/stations.json from real sources (needs internet; run on GitHub Actions).
Sources: NOAA ISD history (id/name/lat/lon/elev/ICAO), AWC station cache (ICAO/WMO/site),
activity check: AWC METAR (last 24h) and OGIMET SYNOP (last 48h). No value is guessed:
missing fields stay null; active=true ONLY if a real report was received."""
import os, csv, io, gzip, json, sys, time, re, datetime as dt, urllib.request, urllib.parse
UA = "MetStat-obs/1.0 (weather research site)"
# ISO2 for ISD 'CTRY' is FIPS; AWC uses ISO2. Region (Iran + neighbours + Gulf/Caspian/Caucasus/Central Asia)
FIPS = {"IR","IZ","AF","PK","TX","UZ","TI","AJ","AM","GG","TU","SA","AE","MU","QA","KU","BA","KZ","SY","IS","JO","YE"}
ISO = {"IR","IQ","AF","PK","TM","UZ","TJ","AZ","AM","GE","TR","SA","AE","OM","QA","KW","BH","KZ","SY","IL","JO","YE"}
def get(url, tries=3, timeout=60):
    for i in range(tries):
        try:
            rq = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(rq, timeout=timeout) as r: return r.read()
        except Exception as e:
            err = e; time.sleep(3 * (i + 1))
    print("FAIL", url, err, file=sys.stderr); return None
def isd():
    b = get("https://www.ncei.noaa.gov/pub/data/noaa/isd-history.csv")
    out = {}
    if not b: return out
    rows_isd = list(csv.DictReader(io.StringIO(b.decode("latin-1"))))
    own5 = {r["USAF"] for r in rows_isd if re.fullmatch(r"\d{5}", r["USAF"]) and not r["USAF"].startswith("99")}   # r193: شمارهٔ WMOهایی که یک ردیف ۵ رقمی دارند
    for r in rows_isd:
        if r["CTRY"] not in FIPS or not r["LAT"] or not r["LON"]: continue
        if r["END"] < (dt.date.today() - dt.timedelta(days=7300 if r["CTRY"] == "IR" else 2000)).strftime("%Y%m%d"): continue   # r193: ایران ۲۰ سال (ایستگاه‌های ISD با END قدیمی ولی هنوز در SYNOP)
        usaf = r["USAF"]
        w5 = usaf if re.fullmatch(r"\d{5}", usaf) and not usaf.startswith("99") else None
        # r193: ایستگاه‌های WMO در ISD معمولاً USAF = شمارهٔ WMO + «0» (۶ رقمی) دارند، مثل انزلی 407180 ← 40718. قبلاً فقط ۵ رقمی می‌پذیرفتیم،
        # پس ایستگاه‌های ایرانی با شمارهٔ ۶ رقمی بدون WMO می‌ماندند و گزارش SYNOP‌شان در obs_fetch «بی‌تطبیق» دور ریخته می‌شد.
        # رقم ششم غیر از ۰ (مثل 407802) زیرایستگاه/ایستگاه دوم است و WMO نیست. فعال بودن را همچنان فقط گزارش واقعی Ogimet تعیین می‌کند.
        w6 = usaf[:5] if re.fullmatch(r"\d{5}0", usaf) and not usaf.startswith("99") and usaf[:5] not in own5 else None
        wmo = w5 or w6
        key = w5 or (r["ICAO"] or usaf)      # کلید/شناسهٔ قبلی دست نمی‌خورد
        out[key] = dict(wmo=wmo, icao=r["ICAO"] or None, name_en=r["STATION NAME"].title(), country_fips=r["CTRY"],
            lat=float(r["LAT"]), lon=float(r["LON"]), elev=float(r["ELEV(M)"]) if r["ELEV(M)"] else None, src=["isd"])
    return out
def awc(db):
    ok = lambda s: isinstance(s.get("lat"), (int, float)) and isinstance(s.get("lon"), (int, float)) and -90 < s["lat"] <= 90 and -180 <= s["lon"] <= 180 and s["lon"] > -99
    b = get("https://aviationweather.gov/data/cache/stations.cache.json.gz")
    if not b: return
    for s in json.loads(gzip.decompress(b)):
        if s.get("country") not in ISO or not ok(s): continue
        icao = s.get("icaoId"); wmo = str(s.get("wmoId") or "").zfill(5) if s.get("wmoId") else None
        k = next((k for k, v in db.items() if (icao and v["icao"] == icao) or (wmo and v["wmo"] == wmo)), None)
        if k is None:
            k = wmo or icao; db[k] = dict(wmo=wmo, icao=icao, name_en=(s.get("site") or "").title(), country_fips=None,
                lat=s.get("lat"), lon=s.get("lon"), elev=s.get("elev"), src=[])
        e = db[k]; e["icao"] = e["icao"] or icao; e["wmo"] = e["wmo"] or wmo
        e["country"] = s.get("country"); e["state"] = s.get("state") or None; e["src"].append("awc")
def manual(db, path="obs_extra_stations.csv", conflicts_out="data/obs/station_conflicts.json"):
    """r193: ایستگاه‌های ایران از پایگاه اطلس سایت (فرم رسمی IRIMO) — ستون‌ها: wmo,name_en,name_fa,lat,lon,elev,country_fips,province,source.
    قواعد (هیچ تطبیقی بر پایهٔ شباهت نام انجام نمی‌شود؛ فقط شمارهٔ WMO + فاصلهٔ مختصات):
      • WMO در db نیست ← ایستگاه اضافه می‌شود (src=manual). فعال‌بودنش را باز هم فقط گزارش واقعی Ogimet تعیین می‌کند.
      • WMO هست و فاصله ≤ ۲۵ km ← همان ایستگاه است؛ فقط فیلدهای خالی (province, name_fa) پر می‌شود.
      • WMO هست، فاصله > ۲۵ km و ردیف موجود فقط از ISD و WMO حدسی از USAF است (بدون ICAO/AWC) ← WMO از ردیف ISD برداشته و ایستگاه رسمی اضافه می‌شود.
      • WMO هست، فاصله > ۲۵ km و ردیف موجود AWC/ICAO دارد ← دست نمی‌خورد و برای بازبینی در station_conflicts.json ثبت می‌شود.
    مختصات ایران باید در ۲۴–۴۰°N و ۴۳–۶۴°E باشد؛ ردیف نامعتبر رد می‌شود."""
    if not os.path.exists(path): return 0
    import math
    def hav(a, b, c, d):
        p = math.pi / 180; x = math.sin((c - a) * p / 2) ** 2 + math.cos(a * p) * math.cos(c * p) * math.sin((d - b) * p / 2) ** 2
        return 2 * 6371 * math.asin(math.sqrt(x))
    byw = {v["wmo"]: k for k, v in db.items() if v.get("wmo")}; add = enr = rep = 0; conf = []
    for r in csv.DictReader(open(path, encoding="utf-8-sig")):
        w = (r.get("wmo") or "").strip()
        try: la, lo = float(r.get("lat") or ""), float(r.get("lon") or "")
        except ValueError: continue
        cc = (r.get("country_fips") or ("IR" if re.fullmatch(r"40[7-9]\d\d", w) else "")).strip()
        if not re.fullmatch(r"\d{5}", w) or not cc or not (-90 < la <= 90 and -180 <= lo <= 180): continue
        if cc == "IR" and not (24 <= la <= 40 and 43 <= lo <= 64): print("manual: مختصات خارج از ایران، رد شد", w, la, lo, file=sys.stderr); continue
        prov = (r.get("province") or "").strip() or None; fa = (r.get("name_fa") or "").strip() or None
        if w in byw:
            v = db[byw[w]]; d = hav(v["lat"], v["lon"], la, lo)
            if d <= 25:
                for fld, val in (("province", prov), ("name_fa", fa)):
                    if val and not v.get(fld): v[fld] = val
                enr += 1; continue
            c = dict(wmo=w, existing=dict(key=byw[w], name=v.get("name_en"), lat=v["lat"], lon=v["lon"], src=v.get("src"), icao=v.get("icao")), atlas=dict(name=r.get("name_en"), lat=la, lon=lo), km=round(d, 1))
            if v.get("src") == ["isd"] and not v.get("icao"): c["action"] = "isd_wmo_removed_atlas_added"; conf.append(c); v["wmo"] = None; rep += 1
            else: c["action"] = "kept_existing_needs_review"; conf.append(c); continue
        # r194: اگر ردیف METAR (ICAO، بدون WMO) در فاصلهٔ کمتر از ۰٫۵ km باشد، همان ایستگاه فیزیکی است ← WMO به همان ردیف اضافه می‌شود
        # (یک ایستگاه، چند شناسه). فاصلهٔ ۰٫۵ تا ۳ km عمداً ادغام نمی‌شود (مثلاً دوشان‌تپه و مهرآباد) و در station_discovery برای بازبینی می‌آید.
        near = None
        for k2, v2 in db.items():
            if v2.get("wmo") or not v2.get("icao") or v2.get("country_fips") not in (cc, None): continue
            d2 = hav(v2["lat"], v2["lon"], la, lo)
            if d2 < 0.5 and (near is None or d2 < near[0]): near = (d2, k2)
        if near:
            v2 = db[near[1]]; v2["wmo"] = w; byw[w] = near[1]
            for fld, val in (("province", prov), ("name_fa", fa)):
                if val and not v2.get(fld): v2[fld] = val
            if "manual" not in v2.setdefault("src", []): v2["src"].append("manual")
            conf.append(dict(wmo=w, action="wmo_attached_to_icao_row", existing=dict(key=near[1], name=v2.get("name_en"), icao=v2.get("icao")), atlas=dict(name=r.get("name_en"), lat=la, lon=lo), km=round(near[0], 2)))
            enr += 1; continue
        el = r.get("elev"); k = w if w not in db else w + "_a"
        db[k] = dict(wmo=w, icao=None, name_en=(r.get("name_en") or "").strip(), name_fa=fa, country_fips=cc, lat=la, lon=lo, elev=float(el) if el not in (None, "") else None, src=["manual"], province=prov); byw[w] = k; add += 1
    if conf:
        os.makedirs(os.path.dirname(conflicts_out) or ".", exist_ok=True); json.dump(conf, open(conflicts_out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"manual: added {add}, enriched {enr}, isd-wmo replaced {rep}, conflicts {len(conf)}"); return add
def metar_active(db):
    ids = sorted({v["icao"] for v in db.values() if v.get("icao")})
    seen = {}
    for i in range(0, len(ids), 200):
        b = get("https://aviationweather.gov/api/data/metar?format=json&hours=24&ids=" + ",".join(ids[i:i+200]))
        if b:
            try:
                for m in json.loads(b): seen[m["icaoId"]] = max(seen.get(m["icaoId"], ""), str(m.get("reportTime") or m.get("obsTime")))
            except Exception as ex: print("metar parse", ex, file=sys.stderr)
    for v in db.values():
        v["metar"] = bool(v.get("icao") and v["icao"] in seen); v["last_metar"] = seen.get(v.get("icao"))
def synop_active(db):
    now = dt.datetime.utcnow(); b0 = (now - dt.timedelta(hours=48)).strftime("%Y%m%d%H00"); e0 = now.strftime("%Y%m%d%H00")
    for v in db.values():
        if not v.get("wmo"): v["synop"] = False; continue
        t = get(f"https://www.ogimet.com/cgi-bin/getsynop?block={v['wmo']}&begin={b0}&end={e0}", tries=2)
        lines = [l for l in (t or b"").decode("latin-1").splitlines() if l.startswith(v["wmo"] + ",")]
        v["synop"] = bool(lines); v["last_synop"] = lines[-1].split(",")[1:5] if lines else None
        time.sleep(2.5)   # be polite to OGIMET
def main():
    global_start = time.time()
    db = isd(); print("ISD rows", len(db)); awc(db); manual(db)
    if not db: sys.exit("no station source reachable - nothing written (no fake data)")
    seen_w = {}                                    # r193: یک WMO فقط روی یک ردیف بماند (ردیف دارای ICAO/AWC ارجح است)
    for k, v in sorted(db.items(), key=lambda kv: (not kv[1].get("icao"), kv[0])):
        w = v.get("wmo")
        if w and w in seen_w: v["wmo"] = None
        elif w: seen_w[w] = k
    metar_active(db)
    if "--no-synop" not in sys.argv: synop_active(db)
    rows = []
    # r193: شناسه‌های قبلی (که سایت، recent.json و CSV روزانه به آن‌ها وابسته‌اند) حفظ می‌شود؛ ایستگاه تازه‌ای که WMO گرفت با شمارهٔ WMO شناسایی می‌شود.
    prev = {}
    try: prev = json.load(open("data/obs/stations.json", encoding="utf-8")).get("stations", [])
    except Exception: pass
    pw = {p["wmo"]: p["id"] for p in prev if p.get("wmo")}; pi = {p["icao"]: p["id"] for p in prev if p.get("icao")}; used = set()
    for k, v in sorted(db.items()):
        v["active"] = bool(v.get("metar") or v.get("synop"))
        cand = pi.get(v.get("icao")) or pw.get(v.get("wmo")) or (v.get("wmo") if v.get("active") else None) or k
        if cand in used: cand = k
        if cand in used: cand = f"{k}_{len(used)}"
        v["id"] = cand; used.add(cand); rows.append(v)
    os.makedirs("data/obs", exist_ok=True)
    json.dump(dict(generated=dt.datetime.utcnow().isoformat() + "Z", n=len(rows), n_active=sum(r["active"] for r in rows),
        sources=["NOAA ISD history", "AWC station cache", "AWC METAR 24h", "OGIMET SYNOP 48h"], stations=rows),
        open("data/obs/stations.json", "w"), ensure_ascii=False, separators=(",", ":"))
    print(len(rows), "stations,", sum(r["active"] for r in rows), "active")
if __name__ == "__main__": main()

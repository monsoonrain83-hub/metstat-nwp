#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""station_discovery/discovery.py — کشف و تطبیق ایستگاه‌ها، حالت REVIEW (r194).

هیچ چیز در data/obs/stations.json یا دیتابیس تولید نوشته نمی‌شود. خروجی فقط گزارش (CSV/JSON/MD) در data/obs/discovery/ است.
قواعد تطبیق: فقط شمارهٔ WMO/ICAO و فاصلهٔ مختصات؛ هیچ‌وقت شباهت نام. شناسه‌های هر منبع حفظ می‌شود.
منابع: atlas (فایل محلی obs_extra_stations.csv، بدون شبکه) و isd_awc (از obs_stations.py، نیازمند اینترنت).
تأیید: ایستگاه جدید فقط وقتی در obs_extra_stations.generated.csv می‌آید که در station_discovery/approvals.csv «accept» شده باشد.
اجرا:  python station_discovery/discovery.py --registry data/obs/stations.json --atlas obs_extra_stations.csv --sources atlas,isd_awc"""
import argparse, csv, json, math, os, re, sys, datetime as dt, collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IRAN_BOX = (24.0, 40.0, 43.0, 64.0)     # lat0, lat1, lon0, lon1
COORD_OK_KM, DUP_KM, NEAR_PROV_KM = 10.0, 3.0, 40.0
COUNTRY_DEFAULT = ["IR"]                # قابل تنظیم با --countries (کدهای FIPS ISD، مثل IR,IZ,TU)

def hav(a, b, c, d):
    p = math.pi / 180; x = math.sin((c - a) * p / 2) ** 2 + math.cos(a * p) * math.cos(c * p) * math.sin((d - b) * p / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(x))
def in_iran(la, lo): return IRAN_BOX[0] <= la <= IRAN_BOX[1] and IRAN_BOX[2] <= lo <= IRAN_BOX[3]
def num(x):
    try: return float(x)
    except (TypeError, ValueError): return None

def read_registry(path):
    j = json.load(open(path, encoding="utf-8")); return j["stations"] if isinstance(j, dict) else j
def read_atlas(path):
    out = []
    for r in csv.DictReader(open(path, encoding="utf-8-sig")):
        la, lo = num(r.get("lat")), num(r.get("lon"))
        if la is None or lo is None: continue
        out.append(dict(source="atlas", wmo=(r.get("wmo") or "").strip() or None, icao=None, name_en=(r.get("name_en") or "").strip(), name_fa=(r.get("name_fa") or "").strip(),
                        lat=la, lon=lo, elev=num(r.get("elev")), province=(r.get("province") or "").strip(), country=(r.get("country_fips") or "IR").strip()))
    return out
def read_isd_awc(countries):
    sys.path.insert(0, ROOT); import obs_stations as O          # شبکه لازم است
    db = O.isd(); O.awc(db); out = []
    for k, v in db.items():
        cc = v.get("country_fips")
        if countries and cc and cc not in countries: continue
        out.append(dict(source="+".join(v.get("src", [])) or "isd_awc", wmo=v.get("wmo"), icao=v.get("icao"), name_en=v.get("name_en") or "", name_fa="",
                        lat=v.get("lat"), lon=v.get("lon"), elev=v.get("elev"), province="", country=cc or "", source_key=k))
    return out

def confidence(s):
    sc = 0
    if s.get("wmo") and re.fullmatch(r"\d{5}", s["wmo"]): sc += 2
    if s.get("icao"): sc += 1
    if s.get("country") == "IR" and in_iran(s["lat"], s["lon"]): sc += 1
    if s["source"].startswith("atlas"): sc += 2
    if "+" in s["source"]: sc += 1
    return "high" if sc >= 5 else ("medium" if sc >= 3 else "low")

def reconcile(reg, src_rows):
    by_w = {r["wmo"]: r for r in reg if r.get("wmo")}; by_i = {r["icao"]: r for r in reg if r.get("icao")}; res = []
    for s in src_rows:
        if s.get("lat") is None or s.get("lon") is None: continue
        m, how = (by_w.get(s["wmo"]), "wmo") if s.get("wmo") and s["wmo"] in by_w else ((by_i.get(s["icao"]), "icao") if s.get("icao") and s["icao"] in by_i else (None, None))
        if m:
            d = hav(s["lat"], s["lon"], m["lat"], m["lon"])
            res.append(dict(status="match" if d <= COORD_OK_KM else "coord_conflict", by=how, km=round(d, 1), s=s, m=m))
        else:
            near = min(((hav(s["lat"], s["lon"], r["lat"], r["lon"]), r) for r in reg), key=lambda t: t[0], default=(None, None))
            if near[1] is not None and near[0] < DUP_KM: res.append(dict(status="possible_duplicate", by="distance", km=round(near[0], 1), s=s, m=near[1]))
            else: res.append(dict(status="new_candidate", by=None, km=None, s=s, m=None))
    return res

def registry_issues(reg):
    iss = []; cw = collections.Counter(r["wmo"] for r in reg if r.get("wmo")); ci = collections.Counter(r["icao"] for r in reg if r.get("icao"))
    for r in reg:
        i = r["id"]
        if r.get("wmo") and cw[r["wmo"]] > 1: iss.append((i, r["name_en"], "duplicate_wmo", r["wmo"]))
        if r.get("icao") and ci[r["icao"]] > 1: iss.append((i, r["name_en"], "duplicate_icao", r["icao"]))
        if r.get("icao") and not r.get("wmo"): iss.append((i, r["name_en"], "icao_without_wmo", r["icao"]))
        if r.get("elev") is None: iss.append((i, r["name_en"], "missing_elevation", ""))
        if r.get("country_fips") == "IR" and not in_iran(r["lat"], r["lon"]): iss.append((i, r["name_en"], "coords_outside_iran", f'{r["lat"]},{r["lon"]}'))
        if r.get("wmo") and not r.get("active"): iss.append((i, r["name_en"], "wmo_not_reporting", r["wmo"]))
    return iss

def coverage_iran(reg, atlas):
    by_w = {r["wmo"]: r for r in reg if r.get("wmo")}; prov = collections.defaultdict(lambda: dict(atlas=0, in_registry=0, active=0, missing=[]))
    for a in atlas:
        if a["country"] != "IR" or not a.get("wmo"): continue
        p = prov[a["province"] or "نامشخص"]; p["atlas"] += 1; r = by_w.get(a["wmo"])
        if r: p["in_registry"] += 1; p["active"] += 1 if r.get("active") else 0
        else: p["missing"].append(f'{a["wmo"]} {a["name_en"]}')
    return prov

def load_approvals(path):
    ap = {}
    if os.path.exists(path):
        for r in csv.DictReader(open(path, encoding="utf-8-sig")):
            if (r.get("wmo") or "").strip(): ap[r["wmo"].strip()] = (r.get("decision") or "").strip().lower()
    return ap

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--registry", default="data/obs/stations.json"); ap.add_argument("--atlas", default="obs_extra_stations.csv")
    ap.add_argument("--sources", default="atlas"); ap.add_argument("--countries", default=",".join(COUNTRY_DEFAULT)); ap.add_argument("--out", default="data/obs/discovery")
    ap.add_argument("--approvals", default=os.path.join(ROOT, "station_discovery", "approvals.csv")); a = ap.parse_args()
    cc = [c for c in a.countries.split(",") if c]; reg = read_registry(a.registry); os.makedirs(a.out, exist_ok=True)
    src = []; limits = []; atlas = read_atlas(a.atlas) if os.path.exists(a.atlas) else []
    for s in a.sources.split(","):
        if s == "atlas": src += atlas
        elif s == "isd_awc":
            try: rows = read_isd_awc(cc); src += rows; (not rows) and limits.append("isd_awc: هیچ ردیفی دریافت نشد (شبکه/منبع در دسترس نبود)")
            except Exception as e: limits.append(f"isd_awc: {type(e).__name__}: {e}")
        else: limits.append(f"منبع ناشناخته: {s}")
    res = reconcile(reg, src); cnt = collections.Counter(r["status"] for r in res); appr = load_approvals(a.approvals)
    rows = []
    for r in res:
        if r["status"] == "match": continue
        s, m = r["s"], r["m"]; conf = confidence(s)
        rows.append([r["status"], conf, s["source"], s.get("wmo") or "", s.get("icao") or "", s["name_en"], s.get("name_fa") or "", s["lat"], s["lon"], s.get("elev") if s.get("elev") is not None else "", s.get("province") or "",
                     (m or {}).get("id", ""), (m or {}).get("name_en", ""), r["km"] if r["km"] is not None else "", appr.get(s.get("wmo") or "", "pending")])
    hdr = ["status", "confidence", "source", "wmo", "icao", "name_en", "name_fa", "lat", "lon", "elev", "province", "registry_id", "registry_name", "km", "decision"]
    rows.sort(key=lambda x: ({"coord_conflict": 0, "possible_duplicate": 1, "new_candidate": 2}[x[0]], {"high": 0, "medium": 1, "low": 2}[x[1]], x[3]))
    with open(os.path.join(a.out, "candidates.csv"), "w", newline="", encoding="utf-8-sig") as f: w = csv.writer(f); w.writerow(hdr); w.writerows(rows)
    iss = registry_issues(reg)
    with open(os.path.join(a.out, "registry_issues.csv"), "w", newline="", encoding="utf-8-sig") as f: w = csv.writer(f); w.writerow(["id", "name", "issue", "detail"]); w.writerows(iss)
    cov = coverage_iran(reg, atlas)
    with open(os.path.join(a.out, "coverage_iran_by_province.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f); w.writerow(["province", "atlas_wmo_stations", "in_registry", "reporting", "missing_count", "missing_list"])
        for p, v in sorted(cov.items(), key=lambda kv: (-len(kv[1]["missing"]), kv[0])): w.writerow([p, v["atlas"], v["in_registry"], v["active"], len(v["missing"]), " | ".join(v["missing"])])
    acc = [r for r in rows if r[0] == "new_candidate" and r[14] == "accept" and r[3]]      # فقط تأییدشده‌ها؛ آستانهٔ اطمینان به‌عنوان اطلاع، نه تصمیم خودکار
    with open(os.path.join(a.out, "obs_extra_stations.generated.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f); w.writerow(["wmo", "name_en", "name_fa", "lat", "lon", "elev", "country_fips", "province", "source"])
        for r in acc: w.writerow([r[3], r[5], r[6], r[7], r[8], r[9], "IR", r[10], f"station_discovery:{r[2]}"])
    summ = dict(generated=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), mode="REVIEW", registry_n=len(reg), registry_active=sum(1 for r in reg if r.get("active")), sources=a.sources,
                source_rows=len(src), status=dict(cnt), high_confidence_new=sum(1 for r in rows if r[0] == "new_candidate" and r[1] == "high"), approved_exported=len(acc), registry_issues=dict(collections.Counter(i[2] for i in iss)), limits=limits)
    json.dump(summ, open(os.path.join(a.out, "summary.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    L = [f"# گزارش کشف ایستگاه (حالت REVIEW) — {summ['generated'][:16]}Z", "", f"- رجیستری: {summ['registry_n']} ایستگاه ({summ['registry_active']} فعال)", f"- منابع: {a.sources} — {len(src)} ردیف منبع",
         f"- نتیجهٔ تطبیق: " + "، ".join(f"{k}={v}" for k, v in sorted(cnt.items())), f"- نامزد جدید با اطمینان بالا: {summ['high_confidence_new']} | تأییدشده برای خروجی: {len(acc)}", ""]
    if limits: L += ["## محدودیت‌ها"] + [f"- {x}" for x in limits] + [""]
    L += ["## پوشش ایران به تفکیک استان (بر پایهٔ ایستگاه‌های WMOدار اطلس)", "", "| استان | اطلس | در رجیستری | گزارش‌دهنده | جاافتاده |", "|---|---|---|---|---|"]
    for p, v in sorted(cov.items(), key=lambda kv: (-len(kv[1]["missing"]), kv[0])): L.append(f"| {p} | {v['atlas']} | {v['in_registry']} | {v['active']} | {len(v['missing'])} |")
    L += ["", "## مشکلات رجیستری", ""] + [f"- {k}: {v}" for k, v in sorted(summ["registry_issues"].items())] + ["", "جزئیات: candidates.csv، registry_issues.csv، coverage_iran_by_province.csv. تأیید: station_discovery/approvals.csv (ستون‌های wmo,decision=accept|reject,note)."]
    open(os.path.join(a.out, "report.md"), "w", encoding="utf-8").write("\n".join(L)); print("\n".join(L[:9]))
    return 0

if __name__ == "__main__": sys.exit(main())

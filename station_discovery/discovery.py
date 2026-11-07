#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Station discovery r196 — REVIEW-only station discovery for Iran and surrounding countries.

Safety:
- Never modifies the production registry.
- Never deletes rows from stations.json.
- Exact-coordinate duplicates are suppressed from candidates.csv and counted in summary.
- All accepted additions are written only to obs_extra_stations.generated.csv.
- Approval is explicit and manual in station_discovery/approvals.csv.

Sources:
- atlas: optional local obs_extra_stations.csv
- isd_awc: existing obs_stations.py module (NOAA ISD + AWC); requires internet

Run:
  python station_discovery/discovery.py \
    --registry data/obs/stations.json \
    --atlas obs_extra_stations.csv \
    --sources atlas,isd_awc
"""
import argparse
import csv
import json
import math
import os
import re
import sys
import datetime as dt
import collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# FIPS country codes used by NOAA ISD. Includes Iran and its immediate/
# broader meteorological surroundings. Override with --countries.
COUNTRY_DEFAULT = [
    "IR", "IZ", "TU", "PK", "AF", "AJ", "AM", "GG", "KZ", "TX",
    "UZ", "TI", "KG", "RS", "SA", "BA", "JO", "SY", "LE", "QA",
    "AE", "MU"
]

COORD_MATCH_KM = 10.0
EXACT_DUP_KM = 0.05       # numerical tolerance for same reported coordinates
POSSIBLE_DUP_KM = 3.0
IRAN_BOX = (24.0, 40.0, 43.0, 64.0)  # lat0, lat1, lon0, lon1

def hav(a, b, c, d):
    p = math.pi / 180.0
    x = (math.sin((c-a)*p/2)**2
         + math.cos(a*p)*math.cos(c*p)*math.sin((d-b)*p/2)**2)
    return 2.0 * 6371.0 * math.asin(math.sqrt(min(1.0, x)))

def in_iran(la, lo):
    return (la is not None and lo is not None
            and IRAN_BOX[0] <= la <= IRAN_BOX[1]
            and IRAN_BOX[2] <= lo <= IRAN_BOX[3])

def num(x):
    try:
        if x is None or str(x).strip() == "":
            return None
        return float(x)
    except (TypeError, ValueError):
        return None

def norm_id(x):
    x = str(x or "").strip()
    return x or None

def read_registry(path):
    with open(path, encoding="utf-8") as f:
        j = json.load(f)
    rows = j["stations"] if isinstance(j, dict) else j
    out = []
    for r in rows:
        q = dict(r)
        q["lat"] = num(q.get("lat"))
        q["lon"] = num(q.get("lon"))
        q["wmo"] = norm_id(q.get("wmo"))
        q["icao"] = norm_id(q.get("icao"))
        out.append(q)
    return out

def read_atlas(path):
    out = []
    if not path or not os.path.exists(path):
        return out
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            la, lo = num(r.get("lat")), num(r.get("lon"))
            if la is None or lo is None:
                continue
            out.append({
                "source": "atlas",
                "wmo": norm_id(r.get("wmo")),
                "icao": norm_id(r.get("icao")),
                "name_en": (r.get("name_en") or "").strip(),
                "name_fa": (r.get("name_fa") or "").strip(),
                "lat": la, "lon": lo, "elev": num(r.get("elev")),
                "province": (r.get("province") or "").strip(),
                "country": (r.get("country_fips") or "IR").strip().upper(),
                "network_type": (r.get("network_type") or "").strip()
            })
    return out

def read_isd_awc(countries):
    # Preserve compatibility with the project's existing data adapter.
    sys.path.insert(0, ROOT)
    import obs_stations as O
    db = O.isd()
    O.awc(db)
    out = []
    for key, v in db.items():
        cc = (v.get("country_fips") or "").strip().upper()
        if countries and cc not in countries:
            continue
        la, lo = num(v.get("lat")), num(v.get("lon"))
        if la is None or lo is None:
            continue
        src = "+".join(v.get("src", [])) or "isd_awc"
        wmo, icao = norm_id(v.get("wmo")), norm_id(v.get("icao"))
        out.append({
            "source": src, "wmo": wmo, "icao": icao,
            "name_en": v.get("name_en") or "", "name_fa": "",
            "lat": la, "lon": lo, "elev": num(v.get("elev")),
            "province": "", "country": cc, "source_key": str(key),
            # A five-digit WMO identifier is a SYNOP-capable lead, not proof
            # that a station currently transmits SYNOP.
            "network_type": ("WMO_SYNOPTIC_CANDIDATE" if wmo and re.fullmatch(r"\d{5}", wmo)
                             else ("ICAO_METAR_CANDIDATE" if icao else "UNCLASSIFIED"))
        })
    return out

def confidence(s):
    score = 0
    if s.get("wmo") and re.fullmatch(r"\d{5}", s["wmo"]):
        score += 2
    if s.get("icao"):
        score += 1
    if s.get("country") == "IR" and in_iran(s.get("lat"), s.get("lon")):
        score += 1
    if s.get("source", "").startswith("atlas"):
        score += 2
    if "+" in s.get("source", ""):
        score += 1
    return "high" if score >= 5 else ("medium" if score >= 3 else "low")

def reconcile(reg, src_rows):
    by_w = {r["wmo"]: r for r in reg if r.get("wmo")}
    by_i = {r["icao"]: r for r in reg if r.get("icao")}
    valid_reg = [r for r in reg if r.get("lat") is not None and r.get("lon") is not None]
    res = []
    for s in src_rows:
        m, how = (None, None)
        if s.get("wmo") and s["wmo"] in by_w:
            m, how = by_w[s["wmo"]], "wmo"
        elif s.get("icao") and s["icao"] in by_i:
            m, how = by_i[s["icao"]], "icao"

        if m:
            d = hav(s["lat"], s["lon"], m["lat"], m["lon"])
            status = "match" if d <= COORD_MATCH_KM else "coord_conflict"
            res.append({"status": status, "by": how, "km": round(d, 3), "s": s, "m": m})
            continue

        nearest = min(
            ((hav(s["lat"], s["lon"], r["lat"], r["lon"]), r) for r in valid_reg),
            key=lambda t: t[0], default=(None, None)
        )
        if nearest[1] is not None and nearest[0] <= EXACT_DUP_KM:
            # Exact/near-zero coordinate duplicate: deliberately excluded
            # from candidate review output; never modifies the registry.
            res.append({"status": "exact_duplicate_suppressed", "by": "distance",
                        "km": round(nearest[0], 3), "s": s, "m": nearest[1]})
        elif nearest[1] is not None and nearest[0] < POSSIBLE_DUP_KM:
            res.append({"status": "possible_duplicate", "by": "distance",
                        "km": round(nearest[0], 3), "s": s, "m": nearest[1]})
        else:
            res.append({"status": "new_candidate", "by": None, "km": None, "s": s, "m": None})
    return res

def registry_issues(reg):
    issues = []
    cw = collections.Counter(r["wmo"] for r in reg if r.get("wmo"))
    ci = collections.Counter(r["icao"] for r in reg if r.get("icao"))
    for r in reg:
        rid, name = r.get("id", ""), r.get("name_en", "")
        if r.get("wmo") and cw[r["wmo"]] > 1:
            issues.append((rid, name, "duplicate_wmo", r["wmo"]))
        if r.get("icao") and ci[r["icao"]] > 1:
            issues.append((rid, name, "duplicate_icao", r["icao"]))
        if r.get("icao") and not r.get("wmo"):
            issues.append((rid, name, "icao_without_wmo", r["icao"]))
        if r.get("elev") is None:
            issues.append((rid, name, "missing_elevation", ""))
        if r.get("country_fips") == "IR" and not in_iran(r.get("lat"), r.get("lon")):
            issues.append((rid, name, "coords_outside_iran", f'{r.get("lat")},{r.get("lon")}'))
        if r.get("wmo") and not r.get("active"):
            issues.append((rid, name, "wmo_not_reporting", r["wmo"]))
    return issues

def load_approvals(path):
    approvals = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                wmo = norm_id(r.get("wmo"))
                country = (r.get("country_fips") or "").strip().upper()
                if wmo:
                    approvals[(country, wmo)] = (r.get("decision") or "").strip().lower()
                    approvals[("", wmo)] = (r.get("decision") or "").strip().lower()
    return approvals

def write_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--registry", default="data/obs/stations.json")
    p.add_argument("--atlas", default="obs_extra_stations.csv")
    p.add_argument("--sources", default="atlas,isd_awc")
    p.add_argument("--countries", default=",".join(COUNTRY_DEFAULT))
    p.add_argument("--out", default="data/obs/discovery")
    p.add_argument("--approvals", default=os.path.join(ROOT, "station_discovery", "approvals.csv"))
    a = p.parse_args()

    countries = {c.strip().upper() for c in a.countries.split(",") if c.strip()}
    os.makedirs(a.out, exist_ok=True)
    reg = read_registry(a.registry)
    atlas = read_atlas(a.atlas)
    src, limits = [], []
    requested = [x.strip() for x in a.sources.split(",") if x.strip()]

    for source in requested:
        if source == "atlas":
            if os.path.exists(a.atlas):
                src.extend(atlas)
            else:
                limits.append(f"atlas: فایل اختیاری وجود ندارد؛ ادامه با سایر منابع: {a.atlas}")
        elif source == "isd_awc":
            try:
                rows = read_isd_awc(countries)
                src.extend(rows)
                if not rows:
                    limits.append("isd_awc: هیچ رکوردی دریافت نشد؛ اتصال شبکه، فیلتر کشورها و obs_stations.py بررسی شود")
            except Exception as e:
                limits.append(f"isd_awc: {type(e).__name__}: {e}")
        else:
            limits.append(f"منبع ناشناخته: {source}")

    results = reconcile(reg, src)
    counts = collections.Counter(x["status"] for x in results)
    approvals = load_approvals(a.approvals)
    visible = []
    for item in results:
        if item["status"] in ("match", "exact_duplicate_suppressed"):
            continue
        s, m = item["s"], item["m"]
        decision = approvals.get(((s.get("country") or "").upper(), s.get("wmo") or ""),
                                 approvals.get(("", s.get("wmo") or ""), "pending"))
        visible.append([
            item["status"], confidence(s), s.get("source", ""),
            s.get("wmo") or "", s.get("icao") or "", s.get("name_en") or "",
            s.get("name_fa") or "", s.get("lat"), s.get("lon"),
            s.get("elev") if s.get("elev") is not None else "",
            s.get("country") or "", s.get("province") or "",
            s.get("network_type") or "", (m or {}).get("id", ""),
            (m or {}).get("name_en", ""), item["km"] if item["km"] is not None else "",
            decision
        ])

    visible.sort(key=lambda r: (
        {"coord_conflict": 0, "possible_duplicate": 1, "new_candidate": 2}.get(r[0], 9),
        {"high": 0, "medium": 1, "low": 2}.get(r[1], 9), r[10], r[3]
    ))
    header = ["status", "confidence", "source", "wmo", "icao", "name_en",
              "name_fa", "lat", "lon", "elev", "country_fips", "province",
              "network_type", "registry_id", "registry_name", "km", "decision"]
    write_csv(os.path.join(a.out, "candidates.csv"), header, visible)

    issues = registry_issues(reg)
    write_csv(os.path.join(a.out, "registry_issues.csv"),
              ["id", "name", "issue", "detail"], issues)

    # Country-level coverage is always available from ISD/AWC even without Atlas.
    country_counts = collections.defaultdict(lambda: collections.Counter())
    for s in src:
        cc = s.get("country") or "UNKNOWN"
        country_counts[cc]["source_rows"] += 1
        if s.get("wmo") and re.fullmatch(r"\d{5}", s["wmo"]):
            country_counts[cc]["wmo_5digit"] += 1
        if s.get("icao"):
            country_counts[cc]["icao"] += 1
    write_csv(os.path.join(a.out, "coverage_by_country.csv"),
              ["country_fips", "source_rows", "wmo_5digit", "icao"],
              [[cc, v["source_rows"], v["wmo_5digit"], v["icao"]]
               for cc, v in sorted(country_counts.items())])

    # Iran province coverage is only claimed when province metadata exists.
    province_counts = collections.defaultdict(lambda: collections.Counter())
    for s in src:
        if s.get("country") == "IR" and s.get("province"):
            province_counts[s["province"]]["source_rows"] += 1
            if s.get("wmo"):
                province_counts[s["province"]]["wmo"] += 1
    write_csv(os.path.join(a.out, "coverage_iran_by_province.csv"),
              ["province", "source_rows", "wmo_stations"],
              [[k, v["source_rows"], v["wmo"]] for k, v in sorted(province_counts.items())])

    # Export only explicitly approved new candidates; retain correct country code.
    exported = []
    for r in visible:
        if r[0] != "new_candidate" or r[16] != "accept" or not r[3]:
            continue
        exported.append([r[3], r[5], r[6], r[7], r[8], r[9], r[10], r[11],
                         f"station_discovery:{r[2]}"])
    write_csv(os.path.join(a.out, "obs_extra_stations.generated.csv"),
              ["wmo", "name_en", "name_fa", "lat", "lon", "elev",
               "country_fips", "province", "source"], exported)

    summary = {
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "mode": "REVIEW",
        "registry_count": len(reg),
        "registry_active_count": sum(1 for r in reg if r.get("active")),
        "sources_requested": requested,
        "countries_filter": sorted(countries),
        "source_rows": len(src),
        "status_counts": dict(counts),
        "visible_candidate_rows": len(visible),
        "exact_coordinate_duplicates_suppressed": counts.get("exact_duplicate_suppressed", 0),
        "new_candidate_high_confidence": sum(1 for r in visible if r[0] == "new_candidate" and r[1] == "high"),
        "approved_exported": len(exported),
        "registry_issue_counts": dict(collections.Counter(x[2] for x in issues)),
        "limits": limits
    }
    with open(os.path.join(a.out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    lines = [
        f"# گزارش کشف ایستگاه‌ها — r196 — {summary['generated_utc']}",
        "",
        "- حالت اجرا: REVIEW؛ رجیستری اصلی تغییر نمی‌کند.",
        f"- تعداد رکوردهای رجیستری: {len(reg)}",
        f"- رکوردهای منابع: {len(src)}",
        f"- تطبیق شناسه‌ای موفق: {counts.get('match', 0)}",
        f"- تکراری با مختصات صفر/تقریباً صفر، حذف‌شده از candidates: {counts.get('exact_duplicate_suppressed', 0)}",
        f"- تکراری احتمالی با فاصله کمتر از {POSSIBLE_DUP_KM} کیلومتر: {counts.get('possible_duplicate', 0)}",
        f"- تعارض مختصات با شناسه یکسان: {counts.get('coord_conflict', 0)}",
        f"- نامزد جدید: {counts.get('new_candidate', 0)}",
        f"- خروجی تأییدشده: {len(exported)}",
        "",
        "## تفسیر شبکه",
        "- WMO پنج‌رقمی به‌عنوان نامزد شبکه سینوپتیک علامت‌گذاری شده است؛ این شناسه به‌تنهایی اثبات‌کننده ارسال فعال SYNOP نیست.",
        "- ICAO بدون WMO به‌عنوان نامزد METAR/فرودگاهی جدا شده است.",
        "- برای تأیید فعالیت واقعی باید زمان آخرین مشاهده و نوع گزارش SYNOP از داده‌های مشاهده‌ای بررسی شود.",
        "",
        "## پوشش کشورها",
        "- فایل coverage_by_country.csv تعداد رکوردهای منبع، WMO پنج‌رقمی و ICAO را به تفکیک کد کشور می‌دهد.",
        "- پوشش استانی ایران فقط در صورت وجود province در Atlas گزارش می‌شود؛ خالی بودن آن به معنی نبود ایستگاه نیست.",
        "",
        "## فایل‌های خروجی",
        "- candidates.csv: نامزدها به‌جز تطبیق‌های موفق و تکراری‌های مختصات صفر.",
        "- registry_issues.csv: ایرادهای قابل بررسی در رجیستری.",
        "- coverage_by_country.csv: پوشش کشورها.",
        "- coverage_iran_by_province.csv: پوشش استانی، در صورت وجود متادیتای استان.",
        "- obs_extra_stations.generated.csv: فقط نامزدهای جدیدی که در approvals.csv صریحاً accept شده‌اند.",
        "- summary.json: شمارش ماشین‌خوان.",
        "",
        "## محدودیت‌ها"
    ]
    lines += [f"- {x}" for x in limits] if limits else ["- محدودیت اجرایی ثبت‌شده‌ای وجود ندارد."]
    lines += [
        "",
        "## تأیید دستی",
        "در station_discovery/approvals.csv برای هر WMO مقدار decision را به accept یا reject تغییر دهید.",
        "هیچ ردیفی صرفاً بر اساس confidence به‌صورت خودکار تأیید نمی‌شود."
    ]
    with open(os.path.join(a.out, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print("\n".join(lines[:16]))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

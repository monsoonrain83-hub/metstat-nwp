#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Station discovery and reconciliation (r195, REVIEW-only).

The registry is never modified. Outputs are written only to --out.
Sources: local Atlas CSV and optional obs_stations.py (ISD/AWC).
"""
import argparse
import collections
import csv
import datetime as dt
import json
import math
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COORD_OK_KM = 10.0
DUP_KM = 3.0

# ISD country FIPS codes. The default intentionally covers Iran and its
# immediate neighbourhood; users can override it with --countries.
DEFAULT_COUNTRIES = ["IR", "IZ", "TU", "AF", "PK", "TX", "AJ", "AM", "GG",
                     "AE", "QA", "BA", "KU", "MU", "SA", "SY", "JO"]
ISO_TO_FIPS = {
    "IR": "IR", "IQ": "IZ", "TR": "TU", "AF": "AF", "PK": "PK",
    "TM": "TX", "AZ": "AJ", "AM": "AM", "GE": "GG", "AE": "AE",
    "QA": "QA", "BH": "BA", "KW": "KU", "OM": "MU", "SA": "SA",
    "SY": "SY", "JO": "JO",
}
COUNTRY_NAMES = {
    "IR": "Iran", "IZ": "Iraq", "TU": "Turkey", "AF": "Afghanistan",
    "PK": "Pakistan", "TX": "Turkmenistan", "AJ": "Azerbaijan",
    "AM": "Armenia", "GG": "Georgia", "AE": "United Arab Emirates",
    "QA": "Qatar", "BA": "Bahrain", "KU": "Kuwait", "MU": "Oman",
    "SA": "Saudi Arabia", "SY": "Syria", "JO": "Jordan",
}


def haversine_km(lat1, lon1, lat2, lon2):
    p = math.pi / 180.0
    a = math.sin((lat2-lat1)*p/2)**2 + math.cos(lat1*p)*math.cos(lat2*p)*math.sin((lon2-lon1)*p/2)**2
    return 2 * 6371.0 * math.asin(min(1.0, math.sqrt(a)))


def number(value):
    try:
        if value is None or str(value).strip() == "":
            return None
        x = float(value)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def norm_id(value):
    if value is None:
        return None
    s = re.sub(r"[^A-Z0-9]", "", str(value).upper())
    return s or None


def get_country(row):
    return (row.get("country_fips") or row.get("country") or "").strip().upper()


def read_registry(path):
    with open(path, encoding="utf-8") as f:
        obj = json.load(f)
    rows = obj.get("stations", []) if isinstance(obj, dict) else obj
    if not isinstance(rows, list):
        raise ValueError("ساختار رجیستری معتبر نیست: stations باید آرایه باشد")
    cleaned = []
    for i, raw in enumerate(rows):
        r = dict(raw)
        r.setdefault("id", r.get("wmo") or f"registry-row-{i+1}")
        r["lat"], r["lon"] = number(r.get("lat")), number(r.get("lon"))
        if r["lat"] is None or r["lon"] is None:
            continue
        r["wmo"] = str(r.get("wmo") or "").strip() or None
        r["icao"] = str(r.get("icao") or "").strip().upper() or None
        cleaned.append(r)
    return cleaned


def read_atlas(path):
    if not os.path.exists(path):
        return [], f"فایل Atlas وجود ندارد: {path}"
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        required = {"lat", "lon"}
        if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
            return [], "ساختار Atlas نامعتبر است؛ ستون‌های lat و lon الزامی‌اند"
        for line, raw in enumerate(reader, 2):
            lat, lon = number(raw.get("lat")), number(raw.get("lon"))
            if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
                continue
            rows.append({
                "source": "atlas", "wmo": str(raw.get("wmo") or "").strip() or None,
                "icao": str(raw.get("icao") or "").strip().upper() or None,
                "name_en": (raw.get("name_en") or "").strip(),
                "name_fa": (raw.get("name_fa") or "").strip(),
                "lat": lat, "lon": lon, "elev": number(raw.get("elev")),
                "province": (raw.get("province") or "").strip(),
                "country": (raw.get("country_fips") or raw.get("country") or "IR").strip().upper(),
                "source_key": (raw.get("source_key") or "").strip() or None,
            })
    return rows, (None if rows else "فایل Atlas موجود است اما هیچ ردیف دارای مختصات معتبر ندارد")


def read_isd_awc(countries):
    sys.path.insert(0, ROOT)
    import obs_stations as O  # supplied by the repository; network access may be required
    db = O.isd()
    O.awc(db)
    out = []
    for key, value in db.items():
        cc = str(value.get("country_fips") or "").strip().upper()
        if not cc:
            iso = str(value.get("country") or "").strip().upper()
            cc = ISO_TO_FIPS.get(iso, iso)
        if countries and cc and cc not in countries:
            continue
        lat, lon = number(value.get("lat")), number(value.get("lon"))
        if lat is None or lon is None:
            continue
        out.append({
            "source": "+".join(value.get("src", [])) or "isd_awc",
            "wmo": str(value.get("wmo") or "").strip() or None,
            "icao": str(value.get("icao") or "").strip().upper() or None,
            "name_en": value.get("name_en") or "", "name_fa": "",
            "lat": lat, "lon": lon, "elev": number(value.get("elev")),
            "province": "", "country": cc, "source_key": str(key),
        })
    return out


def source_identity(row):
    """Return a normalized ISD identity only when it resembles USAF+WBAN.

    Supports common representations such as 999999-12345, 99999912345,
    or a source-key containing those 11 digits. It does not assume that
    arbitrary source keys are ISD identifiers.
    """
    raw = str(row.get("source_key") or row.get("isd_id") or "")
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11:
        return digits
    m = re.search(r"(?<!\d)(\d{6})[-_ ]?(\d{5})(?!\d)", raw)
    return (m.group(1) + m.group(2)) if m else None


def registry_identity(row):
    for key in ("isd_id", "usaf_wban", "usafwban", "source_key"):
        val = row.get(key)
        if val:
            digits = re.sub(r"\D", "", str(val))
            if len(digits) == 11:
                return digits
    usaf, wban = row.get("usaf"), row.get("wban")
    if usaf and wban:
        a, b = re.sub(r"\D", "", str(usaf)), re.sub(r"\D", "", str(wban))
        if len(a) == 6 and len(b) == 5:
            return a + b
    return None


def reconcile(registry, source_rows):
    by_wmo, by_icao, by_isd = {}, {}, {}
    for r in registry:
        if r.get("wmo"):
            by_wmo.setdefault(str(r["wmo"]).strip(), r)
        if r.get("icao"):
            by_icao.setdefault(str(r["icao"]).strip().upper(), r)
        ident = registry_identity(r)
        if ident:
            by_isd.setdefault(ident, r)
    results = []
    for s in source_rows:
        matches = None
        how = None
        if s.get("wmo") and str(s["wmo"]).strip() in by_wmo:
            matches, how = by_wmo[str(s["wmo"]).strip()], "wmo"
        elif s.get("icao") and str(s["icao"]).strip().upper() in by_icao:
            matches, how = by_icao[str(s["icao"]).strip().upper()], "icao"
        else:
            ident = source_identity(s)
            if ident and ident in by_isd:
                matches, how = by_isd[ident], "usaf_wban"
        if matches:
            distance = haversine_km(s["lat"], s["lon"], matches["lat"], matches["lon"])
            status = "match" if distance <= COORD_OK_KM else "coord_conflict"
            results.append({"status": status, "by": how, "km": round(distance, 2), "source": s, "registry": matches})
            continue
        nearest_distance, nearest = min(
            ((haversine_km(s["lat"], s["lon"], r["lat"], r["lon"]), r) for r in registry),
            key=lambda item: item[0], default=(None, None))
        if nearest is not None and nearest_distance <= DUP_KM:
            results.append({"status": "possible_duplicate", "by": "distance", "km": round(nearest_distance, 2), "source": s, "registry": nearest})
        else:
            results.append({"status": "new_candidate", "by": None, "km": None, "source": s, "registry": None})
    return results


def confidence(row):
    score = 0
    if row.get("wmo") and re.fullmatch(r"\d{5}", str(row["wmo"])):
        score += 2
    if row.get("icao"):
        score += 1
    if row.get("country"):
        score += 1
    if row.get("source", "").startswith("atlas"):
        score += 1
    if "+" in row.get("source", ""):
        score += 1
    return "high" if score >= 5 else ("medium" if score >= 3 else "low")


def registry_issues(registry):
    issues = []
    wmo_counts = collections.Counter(r.get("wmo") for r in registry if r.get("wmo"))
    icao_counts = collections.Counter(r.get("icao") for r in registry if r.get("icao"))
    for r in registry:
        if r.get("wmo") and wmo_counts[r["wmo"]] > 1:
            issues.append((r["id"], r.get("name_en", ""), "duplicate_wmo", r["wmo"]))
        if r.get("icao") and icao_counts[r["icao"]] > 1:
            issues.append((r["id"], r.get("name_en", ""), "duplicate_icao", r["icao"]))
        if r.get("icao") and not r.get("wmo"):
            issues.append((r["id"], r.get("name_en", ""), "icao_without_wmo", r["icao"]))
        if r.get("elev") is None:
            issues.append((r["id"], r.get("name_en", ""), "missing_elevation", ""))
        if get_country(r) in ("IR", "IRN") and not (24 <= r["lat"] <= 40 and 43 <= r["lon"] <= 64):
            issues.append((r["id"], r.get("name_en", ""), "coords_outside_iran", f'{r["lat"]},{r["lon"]}'))
        if r.get("wmo") and not r.get("active"):
            issues.append((r["id"], r.get("name_en", ""), "registry_inactive_flag", r["wmo"]))
    return issues


def parse_last_synop(value):
    if not value:
        return None
    try:
        if isinstance(value, (list, tuple)) and len(value) >= 4:
            return dt.datetime(*(int(x) for x in value[:4]), tzinfo=dt.timezone.utc)
        if isinstance(value, str):
            # ISO date/time, or compact YYYYMMDDHH
            s = value.strip()
            if re.fullmatch(r"\d{10}", s):
                return dt.datetime.strptime(s, "%Y%m%d%H").replace(tzinfo=dt.timezone.utc)
            parsed = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
            return parsed.replace(tzinfo=dt.timezone.utc) if parsed.tzinfo is None else parsed.astimezone(dt.timezone.utc)
    except (ValueError, TypeError, OverflowError):
        return None
    return None


def synop_state(row, now):
    last = parse_last_synop(row.get("last_synop"))
    if last is None:
        return "unknown", ""
    age = (now - last).total_seconds() / 3600
    if age < -1:
        return "timestamp_in_future", last.isoformat()
    if age <= 24:
        return "reported_24h", last.isoformat()
    if age <= 168:
        return "reported_7d", last.isoformat()
    if age <= 720:
        return "reported_30d", last.isoformat()
    return "stale_over_30d", last.isoformat()


def country_coverage(registry, source_rows, now):
    grouped = collections.defaultdict(lambda: {"source_records": 0, "registry_stations": 0,
        "registry_active_flag": 0, "synop_24h": 0, "synop_7d": 0, "synop_30d": 0,
        "synop_unknown": 0, "source_wmo": set()})
    for s in source_rows:
        c = s.get("country") or "UNKNOWN"
        grouped[c]["source_records"] += 1
        if s.get("wmo"):
            grouped[c]["source_wmo"].add(str(s["wmo"]))
    seen = collections.defaultdict(set)
    for r in registry:
        c = get_country(r) or "UNKNOWN"
        ident = str(r.get("wmo") or r.get("icao") or r.get("id"))
        if ident in seen[c]:
            continue
        seen[c].add(ident)
        g = grouped[c]
        g["registry_stations"] += 1
        g["registry_active_flag"] += int(bool(r.get("active")))
        state, _ = synop_state(r, now)
        if state == "reported_24h":
            g["synop_24h"] += 1
        elif state in ("reported_7d", "reported_24h"):
            g["synop_7d"] += 1
        elif state in ("reported_30d", "reported_7d", "reported_24h"):
            g["synop_30d"] += 1
        else:
            g["synop_unknown"] += 1
    return grouped


def write_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description="Station discovery (REVIEW-only; registry is never modified)")
    parser.add_argument("--registry", default="data/obs/stations.json")
    parser.add_argument("--atlas", default="obs_extra_stations.csv")
    parser.add_argument("--sources", default="atlas,isd_awc")
    parser.add_argument("--countries", default=",".join(DEFAULT_COUNTRIES), help="ISD/FIPS country codes, comma-separated")
    parser.add_argument("--out", default="data/obs/discovery")
    parser.add_argument("--approvals", default=os.path.join(ROOT, "station_discovery", "approvals.csv"))
    args = parser.parse_args()

    if not os.path.exists(args.registry):
        parser.error(f"فایل رجیستری پیدا نشد: {args.registry}")
    registry = read_registry(args.registry)
    if not registry:
        parser.error("رجیستری هیچ ایستگاه دارای مختصات معتبری ندارد؛ اجرا متوقف شد")

    countries = {x.strip().upper() for x in args.countries.split(",") if x.strip()}
    sources = [x.strip() for x in args.sources.split(",") if x.strip()]
    source_rows, limits = [], []
    atlas_rows, atlas_warning = read_atlas(args.atlas)
    if "atlas" in sources:
        source_rows.extend(atlas_rows)
        if atlas_warning:
            limits.append("atlas: " + atlas_warning)
    if "isd_awc" in sources:
        try:
            rows = read_isd_awc(countries)
            source_rows.extend(rows)
            if not rows:
                limits.append("isd_awc: هیچ ردیف دارای مختصات معتبری دریافت نشد")
        except Exception as exc:
            limits.append(f"isd_awc: {type(exc).__name__}: {exc}")
    unknown = sorted(set(sources) - {"atlas", "isd_awc"})
    for item in unknown:
        limits.append("منبع ناشناخته: " + item)
    if not source_rows:
        limits.append("هشدار بحرانی: هیچ داده‌ای از منابع انتخاب‌شده دریافت نشد؛ فایل‌های خروجی خالی به‌عنوان موفقیت تلقی نشوند")

    results = reconcile(registry, source_rows)
    counts = collections.Counter(x["status"] for x in results)
    approvals = {}
    if os.path.exists(args.approvals):
        with open(args.approvals, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                wmo = (row.get("wmo") or "").strip()
                if wmo:
                    approvals[wmo] = (row.get("decision") or "").strip().lower()

    outdir = args.out
    os.makedirs(outdir, exist_ok=True)
    candidate_rows = []
    for result in results:
        if result["status"] == "match":
            continue
        s, r = result["source"], result["registry"]
        candidate_rows.append([
            result["status"], confidence(s), s.get("source", ""), s.get("country", ""),
            s.get("wmo") or "", s.get("icao") or "", s.get("source_key") or "",
            s.get("name_en", ""), s.get("name_fa", ""), s["lat"], s["lon"],
            s.get("elev") if s.get("elev") is not None else "", s.get("province", ""),
            (r or {}).get("id", ""), (r or {}).get("name_en", ""),
            result["km"] if result["km"] is not None else "",
            approvals.get(s.get("wmo") or "", "pending")])
    candidate_rows.sort(key=lambda x: ({"coord_conflict": 0, "possible_duplicate": 1, "new_candidate": 2}.get(x[0], 9),
                                       {"high": 0, "medium": 1, "low": 2}.get(x[1], 9), x[4]))
    candidate_header = ["status", "confidence", "source", "country_fips", "wmo", "icao", "source_key", "name_en", "name_fa",
                        "lat", "lon", "elev", "province", "registry_id", "registry_name", "distance_km", "decision"]
    write_csv(os.path.join(outdir, "candidates.csv"), candidate_header, candidate_rows)

    issues = registry_issues(registry)
    write_csv(os.path.join(outdir, "registry_issues.csv"), ["id", "name", "issue", "detail"], issues)

    # Coverage based on available registry metadata and fetched source rows;
    # source-derived coverage and registry report freshness remain separate metrics.
    now = dt.datetime.now(dt.timezone.utc)
    coverage = country_coverage(registry, source_rows, now)
    coverage_rows = []
    for code, values in sorted(coverage.items()):
        coverage_rows.append([code, COUNTRY_NAMES.get(code, code), values["source_records"],
                              len(values["source_wmo"]), values["registry_stations"],
                              values["registry_active_flag"], values["synop_24h"],
                              values["synop_7d"], values["synop_30d"], values["synop_unknown"]])
    write_csv(os.path.join(outdir, "coverage_by_country.csv"),
              ["country_fips", "country_name", "source_records", "source_unique_wmo", "registry_stations",
               "registry_active_flag", "synop_reported_24h", "synop_reported_7d_cumulative",
               "synop_reported_30d_cumulative", "synop_freshness_unknown"], coverage_rows)

    # Iran province coverage is only defensible when Atlas has valid province/WMO rows.
    provinces = collections.defaultdict(lambda: {"atlas_wmo": 0, "in_registry": 0, "registry_active_flag": 0, "missing_wmo": []})
    reg_wmo = {str(r.get("wmo")): r for r in registry if r.get("wmo")}
    for row in atlas_rows:
        if row.get("country") not in ("IR", "IRN") or not row.get("wmo"):
            continue
        p = provinces[row.get("province") or "نامشخص"]
        p["atlas_wmo"] += 1
        matched = reg_wmo.get(str(row["wmo"]))
        if matched:
            p["in_registry"] += 1
            p["registry_active_flag"] += int(bool(matched.get("active")))
        else:
            p["missing_wmo"].append(f'{row["wmo"]} {row.get("name_en", "")}')
    province_rows = [[p, v["atlas_wmo"], v["in_registry"], v["registry_active_flag"], len(v["missing_wmo"]), " | ".join(v["missing_wmo"])]
                     for p, v in sorted(provinces.items())]
    write_csv(os.path.join(outdir, "coverage_iran_by_province.csv"),
              ["province", "atlas_wmo_stations", "in_registry", "registry_active_flag", "missing_count", "missing_list"], province_rows)

    approved = [row for row in candidate_rows if row[0] == "new_candidate" and row[16] == "accept" and row[4]]
    generated = [[r[4], r[7], r[8], r[9], r[10], r[11], r[3], r[12], "station_discovery:" + r[2]] for r in approved]
    write_csv(os.path.join(outdir, "obs_extra_stations.generated.csv"),
              ["wmo", "name_en", "name_fa", "lat", "lon", "elev", "country_fips", "province", "source"], generated)

    summary = {
        "generated_utc": now.isoformat(timespec="seconds"), "mode": "REVIEW",
        "registry_stations_with_coordinates": len(registry),
        "registry_active_flag_count": sum(bool(r.get("active")) for r in registry),
        "sources_requested": sources, "source_rows": len(source_rows),
        "status_counts": dict(counts),
        "high_confidence_new_candidates": sum(1 for r in candidate_rows if r[0] == "new_candidate" and r[1] == "high"),
        "approved_exported": len(generated), "registry_issues": dict(collections.Counter(x[2] for x in issues)),
        "iran_provinces_with_atlas_data": len(provinces), "countries_in_coverage": len(coverage),
        "limits": limits,
    }
    with open(os.path.join(outdir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    lines = ["# گزارش کشف ایستگاه‌ها — r195", "", f"زمان اجرا (UTC): {summary['generated_utc']}",
             "", "## خلاصه اجرا", "", f"- حالت: REVIEW؛ رجیستری اصلی تغییر نمی‌کند.",
             f"- ایستگاه‌های رجیستری دارای مختصات: {len(registry)}",
             f"- رکوردهای منابع: {len(source_rows)}",
             f"- نتایج تطبیق: " + (", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "بدون نتیجه"),
             f"- نامزد جدید با اطمینان بالا: {summary['high_confidence_new_candidates']}",
             f"- ایستگاه تأییدشده برای خروجی: {len(generated)}", ""]
    if limits:
        lines += ["## محدودیت‌ها و هشدارها", ""] + [f"- {x}" for x in limits] + [""]
    lines += ["## پوشش کشورها", "", "| کد FIPS | کشور | منبع | WMO یکتا در منبع | رجیستری | active در رجیستری | SYNOP ۲۴ساعت | SYNOP ۷روز تجمعی | SYNOP ۳۰روز تجمعی | تازگی نامشخص |",
              "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for row in coverage_rows:
        lines.append("| " + " | ".join(str(x) for x in row) + " |")
    lines += ["", "توجه: ستون‌های SYNOP از فیلد `last_synop` رجیستری محاسبه می‌شوند؛ این برنامه در r195 اتصال مستقلی برای واکشی پیام‌های زنده SYNOP ایجاد نمی‌کند. `active` نیز صرفاً پرچم رجیستری است، نه اثبات گزارش‌دهی زنده.",
              "", "## پوشش استانی ایران", ""]
    if not province_rows:
        lines.append("داده قابل محاسبه‌ای وجود ندارد. فایل Atlas باید ردیف‌های معتبر دارای lat، lon، wmo و province داشته باشد؛ در غیر این صورت جدول خالی است و این وضعیت در گزارش پنهان نمی‌شود.")
    else:
        lines += ["| استان | اطلس WMOدار | در رجیستری | پرچم active رجیستری | جاافتاده |", "|---|---:|---:|---:|---:|"]
        for row in province_rows:
            lines.append(f"| {row[0]} | {row[1]} | {row[2]} | {row[3]} | {row[4]} |")
    lines += ["", "## فایل‌های خروجی", "", "- `candidates.csv`: نامزدها، تعارض مختصات و موارد تکراری احتمالی.",
              "- `registry_issues.csv`: کیفیت و ناسازگاری‌های رجیستری.",
              "- `coverage_by_country.csv`: پوشش کشوری بر اساس منابع اجراشده و رجیستری.",
              "- `coverage_iran_by_province.csv`: پوشش استانی فقط در صورت وجود داده Atlas معتبر.",
              "- `obs_extra_stations.generated.csv`: فقط نامزدهای جدید دارای تصمیم accept.",
              "- `summary.json`: خلاصه ماشینی اجرا.", ""]
    with open(os.path.join(outdir, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n".join(lines[:14]))
    return 0


if __name__ == "__main__":
    sys.exit(main())

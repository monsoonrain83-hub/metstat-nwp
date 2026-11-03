#!/usr/bin/env python3
"""Stage 1: build data/obs/stations.json from real sources (needs internet; run on GitHub Actions).
Sources: NOAA ISD history (id/name/lat/lon/elev/ICAO), AWC station cache (ICAO/WMO/site),
activity check: AWC METAR (last 24h) and OGIMET SYNOP (last 48h). No value is guessed:
missing fields stay null; active=true ONLY if a real report was received."""
import csv, io, gzip, json, sys, time, re, datetime as dt, urllib.request, urllib.parse
UA = "MetStat-obs/1.0 (weather research site)"
# ISO2 for ISD 'CTRY' is FIPS; AWC uses ISO2. Region (Iran + neighbours + Gulf/Caspian/Caucasus/Central Asia)
FIPS = {"IR","IZ","AF","PK","TX","UZ","TI","AJ","AM","GG","TU","SA","AE","MU","QA","KU","BA","KZ","SY","IS","JO","RS","YE","IN"}
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
    for r in csv.DictReader(io.StringIO(b.decode("latin-1"))):
        if r["CTRY"] not in FIPS or not r["LAT"] or not r["LON"]: continue
        if r["END"] < (dt.date.today() - dt.timedelta(days=400)).strftime("%Y%m%d"): continue
        usaf = r["USAF"]
        wmo = usaf if re.fullmatch(r"\d{5}", usaf) and not usaf.startswith("99") else None
        key = wmo or (r["ICAO"] or usaf)
        out[key] = dict(wmo=wmo, icao=r["ICAO"] or None, name_en=r["STATION NAME"].title(), country_fips=r["CTRY"],
            lat=float(r["LAT"]), lon=float(r["LON"]), elev=float(r["ELEV(M)"]) if r["ELEV(M)"] else None, src=["isd"])
    return out
def awc(db):
    b = get("https://aviationweather.gov/data/cache/stations.cache.json.gz")
    if not b: return
    for s in json.loads(gzip.decompress(b)):
        if s.get("country") not in ISO: continue
        icao = s.get("icaoId"); wmo = str(s.get("wmoId") or "").zfill(5) if s.get("wmoId") else None
        k = next((k for k, v in db.items() if (icao and v["icao"] == icao) or (wmo and v["wmo"] == wmo)), None)
        if k is None:
            k = wmo or icao; db[k] = dict(wmo=wmo, icao=icao, name_en=(s.get("site") or "").title(), country_fips=None,
                lat=s.get("lat"), lon=s.get("lon"), elev=s.get("elev"), src=[])
        e = db[k]; e["icao"] = e["icao"] or icao; e["wmo"] = e["wmo"] or wmo
        e["country"] = s.get("country"); e["state"] = s.get("state") or None; e["src"].append("awc")
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
    db = isd(); awc(db)
    if not db: sys.exit("no station source reachable - nothing written (no fake data)")
    metar_active(db)
    if "--no-synop" not in sys.argv: synop_active(db)
    rows = []
    for k, v in sorted(db.items()):
        v["active"] = bool(v.get("metar") or v.get("synop")); v["id"] = k; rows.append(v)
    json.dump(dict(generated=dt.datetime.utcnow().isoformat() + "Z", n=len(rows), n_active=sum(r["active"] for r in rows),
        sources=["NOAA ISD history", "AWC station cache", "AWC METAR 24h", "OGIMET SYNOP 48h"], stations=rows),
        open("data/obs/stations.json", "w"), ensure_ascii=False, separators=(",", ":"))
    print(len(rows), "stations,", sum(r["active"] for r in rows), "active")
if __name__ == "__main__": main()

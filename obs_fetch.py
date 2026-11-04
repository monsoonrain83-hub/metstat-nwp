#!/usr/bin/env python3
"""MetStat observations ingest. Real data only: AWC METAR (already decoded by AWC) + OGIMET SYNOP (decoded by obs_decode).
Outputs (under data/obs/): recent.json (rolling 80 h), latest.json (per-station latest), fetch_log.json,
and with --daily: daily/YYYY-MM.csv (append, idempotent) + daily_latest.json.
Daily window: 24 h ending 06:00 UTC (= 09:30 Iran time) on date D."""
import os, sys, json, csv, time, datetime as dt, urllib.request, urllib.parse
from obs_decode import decode_synop
UA = "MetStat-obs/1.0 (weather research site)"; OUT = "data/obs"; UTC = dt.timezone.utc
STATES = ["Iran", "Iraq", "Turkey", "Azerbaijan", "Armenia", "Georgia", "Turkmenistan", "Uzbekistan", "Tajikistan", "Afghanistan", "Pakistan", "Saudi_Arabia", "Oman", "United_Arab_Emirates", "Qatar", "Kuwait", "Bahrain", "Kazakhstan", "Syria", "Jordan", "Yemen"]
def get(url, tries=3, timeout=90):
    err = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=timeout) as r: return r.read()
        except Exception as e: err = e; time.sleep(4 * (i + 1))
    print("FAIL", url[:120], err, file=sys.stderr); return None
def now(): return dt.datetime.now(UTC)
def iso(t): return t.strftime("%Y-%m-%dT%H:%MZ")
def load(p, d):
    try: return json.load(open(p))
    except Exception: return d
def main():
    os.makedirs(OUT + "/daily", exist_ok=True)
    S = load(OUT + "/stations.json", {}).get("stations", [])
    by_w = {s["wmo"]: s["id"] for s in S if s.get("wmo")}; by_i = {s["icao"]: s["id"] for s in S if s.get("icao")}
    meta = {s["id"]: s for s in S}
    rec = load(OUT + "/recent.json", {"obs": []})["obs"]; seen = {(o["id"], o["src"], o["time"]) for o in rec}
    log = {"time": iso(now()), "states": {}, "metar": 0, "synop": 0, "synop_unmatched": 0}
    # ---- METAR (AWC JSON, ICAO list) ----
    ids = sorted(by_i)
    for i in range(0, len(ids), 200):
        b = get("https://aviationweather.gov/api/data/metar?format=json&hours=48&ids=" + ",".join(ids[i:i + 200]))
        if not b: continue
        try: arr = json.loads(b)
        except Exception: continue
        for m in arr:
            sid = by_i.get(m.get("icaoId"));
            if not sid or m.get("obsTime") is None: continue
            t = iso(dt.datetime.fromtimestamp(int(m["obsTime"]), UTC)); k = (sid, "metar", t)
            if k in seen: continue
            vis = m.get("visib"); 
            try: vis = float(str(vis).replace("+", "")) * 1.609 if vis not in (None, "") else None
            except Exception: vis = None
            kt = lambda v: round(v * 0.514444, 1) if isinstance(v, (int, float)) else None
            rec.append({"id": sid, "src": "metar", "time": t, "t": m.get("temp"), "td": m.get("dewp"), "dd": m.get("wdir") if isinstance(m.get("wdir"), (int, float)) else None,
                        "ff_ms": kt(m.get("wspd")), "gust_ms": kt(m.get("wgst")), "slp": m.get("slp"), "p": m.get("altim"), "vis_km": vis and round(vis, 1), "raw": m.get("rawOb")})
            seen.add(k); log["metar"] += 1
    # ---- SYNOP (OGIMET, per state; fall back to per-WMO for Iran if state query returns nothing) ----
    b0 = (now() - dt.timedelta(hours=50)).strftime("%Y%m%d%H00"); e0 = now().strftime("%Y%m%d%H00")
    def ingest(text):
        n = 0
        for ln in text.splitlines():
            p = ln.split(",", 6)
            if len(p) < 7 or not p[0].isdigit(): continue
            sid = by_w.get(p[0])
            if not sid: log["synop_unmatched"] += 1; continue
            try: t = iso(dt.datetime(int(p[1]), int(p[2]), int(p[3]), int(p[4]), int(p[5]), tzinfo=UTC))
            except Exception: continue
            k = (sid, "synop", t)
            if k in seen: continue
            d = decode_synop(p[6]);
            if not d: continue
            d.pop("wmo", None); d.update({"id": sid, "src": "synop", "time": t, "raw": p[6].strip()}); rec.append(d); seen.add(k); n += 1
        return n
    for st in STATES:
        b = get(f"https://www.ogimet.com/cgi-bin/getsynop?state={urllib.parse.quote(st)}&begin={b0}&end={e0}&lang=en", tries=2)
        n = ingest(b.decode("latin-1")) if b else -1; log["states"][st] = n; log["synop"] += max(n, 0); time.sleep(3)
    if log["states"].get("Iran", 0) <= 0:   # fallback: per Iranian WMO block
        for s in S:
            if (s.get("country") == "IR" or s.get("country_fips") == "IR") and s.get("wmo"):
                b = get(f"https://www.ogimet.com/cgi-bin/getsynop?block={s['wmo']}&begin={b0}&end={e0}", tries=1)
                if b: log["synop"] += ingest(b.decode("latin-1"))
                time.sleep(2.5)
        log["fallback_per_block"] = True
    cut = iso(now() - dt.timedelta(hours=80)); rec = [o for o in rec if o["time"] >= cut]; rec.sort(key=lambda o: (o["id"], o["time"]))
    json.dump({"obs": rec}, open(OUT + "/recent.json", "w"), ensure_ascii=False, separators=(",", ":"))
    # ---- latest per station ----
    lat = {}
    for o in rec:
        L = lat.setdefault(o["id"], {}); 
        if o["src"] not in L or o["time"] > L[o["src"]]["time"]: L[o["src"]] = o
    json.dump({"generated": iso(now()), "n": len(lat), "stations": lat}, open(OUT + "/latest.json", "w"), ensure_ascii=False, separators=(",", ":"))
    json.dump(log, open(OUT + "/fetch_log.json", "w"), indent=1); print(log)
    if "--daily" in sys.argv: daily(rec, meta)
def daily(rec, meta):
    D = now().date(); end = dt.datetime(D.year, D.month, D.day, 6, 0, tzinfo=UTC); beg = end - dt.timedelta(hours=24)
    if now() < end + dt.timedelta(minutes=30): D -= dt.timedelta(days=1); end -= dt.timedelta(days=1); beg -= dt.timedelta(days=1)
    ds = D.isoformat(); fn = f"{OUT}/daily/{ds[:7]}.csv"; hdr = ["date", "id", "wmo", "icao", "name", "rr24", "rr24_src", "tmax", "tmax_src", "tmin", "tmin_src", "wmax_ms", "wmax_src", "n_obs"]
    old = list(csv.reader(open(fn))) if os.path.exists(fn) else [hdr]
    if any(r and r[0] == ds for r in old[1:]): print("daily exists", ds); return
    W = [o for o in rec if iso(beg) < o["time"] <= iso(end)]; rows = []; by = {}
    for o in W: by.setdefault(o["id"], []).append(o)
    for sid, L in by.items():
        m = meta.get(sid, {}); rr = rs = tx = txs = tn = tns = None
        e6 = [o for o in L if o["src"] == "synop" and o["time"] == iso(end)]
        for o in e6:
            if o.get("rr24_7") is not None: rr, rs = o["rr24_7"], "synop-7RRRR"
            elif o.get("rr") is not None and o.get("rr_h") == 24: rr, rs = o["rr"], "synop-6RRRtR"
        X = [o["tmax"] for o in L if o.get("tmax") is not None]; N = [o["tmin"] for o in L if o.get("tmin") is not None]
        if X: tx, txs = max(X), "synop-sec3"
        if N: tn, tns = min(N), "synop-sec3"
        T = [(o["time"][:13], o["t"]) for o in L if o.get("t") is not None]; hrs = {h for h, _ in T}
        if tx is None and len(hrs) >= 8: tx, txs = max(v for _, v in T), "obs-hourly"
        if tn is None and len(hrs) >= 8: tn, tns = min(v for _, v in T), "obs-hourly"
        Wd = [v for o in L for v in (o.get("gust_ms"), o.get("ff_ms")) if v is not None]
        wm = max(Wd) if Wd else None
        if rr is None and tx is None and tn is None and wm is None: continue
        rows.append([ds, sid, m.get("wmo") or "", m.get("icao") or "", m.get("name_en") or "", rr, rs or "", tx, txs or "", tn, tns or "", wm, "obs" if wm is not None else "", len(L)])
    with open(fn, "w", newline="") as f: w = csv.writer(f); w.writerows(old + rows)
    json.dump({"date": ds, "window_utc": [iso(beg), iso(end)], "header": hdr, "rows": rows}, open(OUT + "/daily_latest.json", "w"), ensure_ascii=False, separators=(",", ":"))
    print("daily", ds, len(rows))
if __name__ == "__main__": main()

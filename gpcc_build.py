#!/usr/bin/env python3
"""GPCC V2025 ماهانه ← برش منطقه‌ای فشرده برای سایت (کم‌حجم؛ هیچ آرشیو جهانی روی هاست نمی‌ماند).
روش: هر بستهٔ ۵‌ساله (nc.gz) در یک پوشهٔ موقت دانلود، فقط مستطیل موردنظر استخراج و فایل موقت پاک می‌شود؛
قطعه‌های استخراج‌شده در cache می‌مانند و فقط بستهٔ تغییرکرده دوباره دانلود می‌شود.
خروجی: gpcc_<region>.bin (int16 گرم‌شده با gzip، بُعد [زمان][عرض][طول]، گام ۰٫۱ mm) + gpcc_<region>.json (متادیتا).
"""
import argparse, gzip, hashlib, io, json, os, re, shutil, sys, tempfile, time, datetime as dt
import numpy as np

BASE = "https://opendata.dwd.de/climate_environment/GPCC/GPCC_Precipitation_Analysis_Monthly/Version_2025/{res}_degree/"
RESDIR = {"0.25": "025", "0.5": "050", "1.0": "100", "2.5": "250"}
NODATA = -32768

def log(*a): print(*a, flush=True)

def list_remote(url):
    import requests
    r = requests.get(url, timeout=60); r.raise_for_status()
    names = sorted(set(re.findall(r'href="([^"?/][^"]*?\.nc(?:\.gz)?)"', r.text)))
    out = []
    for n in names:
        h = requests.head(url + n, timeout=60, allow_redirects=True)
        out.append({"name": n, "url": url + n, "size": int(h.headers.get("Content-Length", 0)), "mod": h.headers.get("Last-Modified", "")})
    return out

def list_local(d):
    out = []
    for n in sorted(os.listdir(d)):
        if re.search(r"\.nc(\.gz)?$", n):
            p = os.path.join(d, n); out.append({"name": n, "url": p, "size": os.path.getsize(p), "mod": str(int(os.path.getmtime(p)))})
    return out

def _open(path):
    try:
        from netCDF4 import Dataset
        ds = Dataset(path); g = lambda k: ds.variables[k]; names = list(ds.variables)
        def arr(v): return np.ma.filled(np.ma.asarray(v[:]).astype("float64"), np.nan), {k: getattr(v, k) for k in v.ncattrs()}
        return names, (lambda k: arr(ds.variables[k])), ds.close
    except ImportError:
        from scipy.io import netcdf_file
        ds = netcdf_file(path, mmap=False); names = list(ds.variables)
        def arr(v):
            a = np.array(v.data, dtype="float64"); at = {k: (v.__dict__[k].decode() if isinstance(v.__dict__[k], bytes) else v.__dict__[k]) for k in v.__dict__ if not k.startswith("_") and k not in ("data", "isrec", "dimensions", "maskandscale")}
            if "_FillValue" in at: a[a == at["_FillValue"]] = np.nan
            return a, at
        return names, (lambda k: arr(ds.variables[k])), ds.close

def month_index(times, attrs):
    u = str(attrs.get("units", "")); m = re.match(r"\s*(days|hours|months)\s+since\s+(\d{4})-(\d{1,2})-(\d{1,2})", u)
    if not m: raise RuntimeError(f"واحد زمان ناشناخته: {u!r}")
    unit, y, mo, d = m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4)); base = dt.datetime(y, mo, d); out = []
    for t in times:
        if unit == "months": k = (y * 12 + mo - 1) + int(round(t))
        else:
            x = base + (dt.timedelta(days=float(t)) if unit == "days" else dt.timedelta(hours=float(t))); k = x.year * 12 + x.month - 1
        out.append(k)
    return np.array(out, dtype=int)

def extract(path, bbox):
    """bbox = (south, north, west, east) ← (k_months[], lat[], lon[], data[t,lat,lon] mm/month)"""
    names, get, close = _open(path)
    pick = lambda c: next((n for n in c if n in names), None)
    vlat, vlon, vt, vp = pick(["lat", "latitude"]), pick(["lon", "longitude"]), pick(["time"]), pick(["precip", "precipitation", "pre", "pr"])
    if not all([vlat, vlon, vt, vp]): raise RuntimeError(f"متغیرهای لازم پیدا نشد؛ موجود: {names}")
    lat, _ = get(vlat); lon, _ = get(vlon); tm, ta = get(vt); P, pa = get(vp)
    log("   متغیرها:", names, "| واحد بارش:", pa.get("units"), "| شکل:", P.shape)
    s, n, w, e = bbox; ia = np.where((lat >= s) & (lat <= n))[0]; ja = np.where((lon >= w) & (lon <= e))[0]
    if not len(ia) or not len(ja): raise RuntimeError("محدوده بیرون از شبکهٔ فایل است")
    dims_ok = P.ndim == 3
    if not dims_ok: raise RuntimeError(f"بُعد غیرمنتظره: {P.shape}")
    A = P[:, ia.min():ia.max() + 1, ja.min():ja.max() + 1].astype("float32"); la = lat[ia.min():ia.max() + 1]; lo = lon[ja.min():ja.max() + 1]
    A[(A < 0) | (A > 1e5)] = np.nan
    if la[0] > la[-1]: A = A[:, ::-1, :]; la = la[::-1]
    close(); return month_index(tm, ta), la, lo, A

def build(files, bbox, cache, tmp_root, refresh_last, log=log):
    os.makedirs(cache, exist_ok=True); pieces = {}; lat = lon = None; peak = 0; dl_bytes = 0; used = []
    for i, f in enumerate(files):
        key = hashlib.md5((f["name"] + str(f["size"]) + f["mod"] + str(bbox)).encode()).hexdigest()[:16]; cf = os.path.join(cache, key + ".npz")
        newest = i >= len(files) - refresh_last
        if os.path.exists(cf) and not newest:
            z = np.load(cf); log("♻︎ از cache:", f["name"]); k, la, lo, A = z["k"], z["lat"], z["lon"], z["A"]
        else:
            free = shutil.disk_usage(tmp_root).free; need = f["size"] * 8 + 50e6
            if free < need: raise RuntimeError(f"فضای موقت کافی نیست برای {f['name']}: آزاد {free/1e6:.0f}MB، لازم ≈ {need/1e6:.0f}MB — اجرا نشد")
            with tempfile.TemporaryDirectory(dir=tmp_root) as wd:
                gz = os.path.join(wd, f["name"])
                if re.match(r"https?://", f["url"]):
                    import requests
                    with requests.get(f["url"], stream=True, timeout=300) as r:
                        r.raise_for_status()
                        with open(gz, "wb") as o:
                            for ch in r.iter_content(1 << 20): o.write(ch)
                else: shutil.copy(f["url"], gz)
                dl_bytes += os.path.getsize(gz); nc = gz
                if gz.endswith(".gz"):
                    nc = gz[:-3]
                    with gzip.open(gz, "rb") as a, open(nc, "wb") as b: shutil.copyfileobj(a, b)
                    os.remove(gz)
                peak = max(peak, os.path.getsize(nc) + f["size"])
                log("↓", f["name"], f"{f['size']/1e6:.1f}MB فشرده →", f"{os.path.getsize(nc)/1e6:.0f}MB"); k, la, lo, A = extract(nc, bbox)
            np.savez_compressed(cf, k=k, lat=la, lon=lo, A=A)
        if lat is None: lat, lon = la, lo
        elif len(la) != len(lat) or len(lo) != len(lon) or not np.allclose(la, lat) or not np.allclose(lo, lon): raise RuntimeError("شبکهٔ فایل‌ها یکسان نیست")
        for j, kk in enumerate(k): pieces[int(kk)] = A[j]
        used.append({"name": f["name"], "bytes": f["size"], "mod": f["mod"]})
    ks = sorted(pieces); k0, k1 = ks[0], ks[-1]; nt = k1 - k0 + 1; D = np.full((nt, len(lat), len(lon)), np.nan, "float32"); gaps = []
    for kk in range(k0, k1 + 1):
        if kk in pieces: D[kk - k0] = pieces[kk]
        else: gaps.append(f"{kk//12}-{kk%12+1:02d}")
    I = np.where(np.isnan(D), NODATA, np.clip(np.round(D * 10), 0, 32000)).astype("<i2")
    return I, lat, lon, k0, nt, gaps, used, peak, dl_bytes

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--list", action="store_true"); ap.add_argument("--res", default="0.25"); ap.add_argument("--region", default="iran")
    ap.add_argument("--bbox", default="24,41,43,64", help="جنوب,شمال,غرب,شرق"); ap.add_argument("--src-dir"); ap.add_argument("--cache", default="gpcc_cache"); ap.add_argument("--out", default=".")
    ap.add_argument("--refresh-last", type=int, default=1); ap.add_argument("--max-final-mb", type=float, default=60); ap.add_argument("--upload"); ap.add_argument("--host"); ap.add_argument("--key"); a = ap.parse_args()
    if a.upload:
        import requests
        for ext, ct in ((".bin", "application/octet-stream"), (".json", "application/json")):   # اول bin بعد json (متادیتا آخر تا ناسازگاری پیش نیاید)
            p = os.path.join(a.upload, f"gpcc_{a.region}{ext}")
            with open(p, "rb") as f: r = requests.post(f'{a.host.rstrip("/")}/nwp_upload.php?a=gpccput&key={requests.utils.quote(a.key)}', data={"name": os.path.basename(p)}, files={"f": (os.path.basename(p), f, ct)}, timeout=600)
            log("upload", os.path.basename(p), r.status_code, r.text[:160]); r.raise_for_status()
        return
    bbox = tuple(float(x) for x in a.bbox.split(",")); url = BASE.format(res=RESDIR[a.res])
    files = list_local(a.src_dir) if a.src_dir else list_remote(url)
    log(f"{len(files)} فایل؛ مجموع فشرده {sum(f['size'] for f in files)/1e6:.0f} MB"); [log("  ", f["name"], f"{f['size']/1e6:.1f}MB") for f in files]
    if a.list: return
    os.makedirs(a.out, exist_ok=True); I, lat, lon, k0, nt, gaps, used, peak, dl = build(files, bbox, a.cache, tempfile.gettempdir(), a.refresh_last)
    raw = I.tobytes(); gzb = gzip.compress(raw, 9); binp = os.path.join(a.out, f"gpcc_{a.region}.bin")
    if len(gzb) > a.max_final_mb * 1e6: raise RuntimeError(f"خروجی {len(gzb)/1e6:.0f}MB از سقف {a.max_final_mb}MB بیشتر است")
    open(binp, "wb").write(gzb)
    meta = {"v": 1, "product": "GPCC Precipitation Analysis Monthly V2025 (Full Data + Monitoring)", "res": float(a.res), "region": a.region, "bbox": bbox, "lat0": float(lat[0]), "dlat": float(lat[1] - lat[0]), "nlat": int(len(lat)), "lon0": float(lon[0]), "dlon": float(lon[1] - lon[0]), "nlon": int(len(lon)),
        "t0": f"{k0//12}-{k0%12+1:02d}", "nt": int(nt), "scale": 0.1, "nodata": NODATA, "unit": "mm/month", "built": dt.datetime.utcnow().isoformat() + "Z", "src": url, "files": used, "gaps": gaps[:200], "ngaps": len(gaps),
        "bytes_gz": len(gzb), "peak_temp_bytes": int(peak), "download_bytes": int(dl), "quality": "تحلیل شبکه‌ای از ایستگاه‌ها؛ واقعیت مشاهده‌ای نیست. آخرین ماه‌ها دیرتر (حدود ۲ ماه) منتشر می‌شوند و ممکن است پس از بازبینی تغییر کنند.",
        "license": "شرایط استفادهٔ DWD/GPCC؛ ذکر منبع الزامی (DOI در صفحهٔ دانلود)."}
    json.dump(meta, open(os.path.join(a.out, f"gpcc_{a.region}.json"), "w"), ensure_ascii=False, separators=(",", ":"))
    log(f"✓ {binp} {len(gzb)/1e6:.2f}MB؛ شبکه {len(lat)}×{len(lon)}، {nt} ماه از {meta['t0']}؛ حفره‌ها: {len(gaps)}؛ بیشینهٔ فضای موقت ≈ {peak/1e6:.0f}MB؛ دانلود {dl/1e6:.0f}MB")

if __name__ == "__main__": main()

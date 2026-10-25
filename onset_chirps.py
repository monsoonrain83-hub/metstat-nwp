#!/usr/bin/env python3
"""CHIRPS روزانه (p25) ← برش ایران ← تاریخ آغاز/پایان فصل بارش با چند روش ← فایل کم‌حجم برای سایت.
حالت‌ها: --list (بررسی فایل‌ها)، --build (دانلود/ساخت)، --upload (ارسال به هاست)، --mock (آزمون با داده ساختگی؛ بدون شبکه).
خروجی: onset_<region>.json + onset_<region>.bin (gzip؛ int16 با ترتیب [روش][۰=آغاز،۱=پایان][سال][عرض][طول]؛ -1 = تعریف نشد).
⚠ CHIRPS ترکیب ماهواره و ایستگاه است؛ در ایران (کوهستان، بارش برف) خطای بارش روزانه زیاد است. نتیجه راهنماست، نه جایگزین ایستگاه.
"""
import argparse, gzip, io, json, os, re, sys, time, datetime as dt
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import onset_methods as OM

URL = "https://data.chc.ucsb.edu/products/CHIRPS-2.0/global_daily/netcdf/p25/chirps-v2.0.{y}.days_p25.nc"
LIST_URL = "https://data.chc.ucsb.edu/products/CHIRPS-2.0/global_daily/netcdf/p25/"
NODATA = -32768
def log(*a): print(*a, flush=True)

SRCDIR = None   # برای آزمون: پوشهٔ فایل‌های محلی به‌جای دانلود

def _read_nc(path, bbox):
    S, N, W, E = bbox
    try:
        from netCDF4 import Dataset
        ds = Dataset(path); rd = lambda k: np.ma.filled(np.ma.asarray(ds.variables[k][:]).astype("float64"), np.nan); close = ds.close
        pre = ds.variables["precip"]
    except ImportError:
        from scipy.io import netcdf_file
        ds = netcdf_file(path, mmap=False); rd = lambda k: np.array(ds.variables[k].data, dtype="float64"); close = ds.close; pre = ds.variables["precip"]
    lat = rd("latitude"); lon = rd("longitude"); i = np.where((lat >= S) & (lat <= N))[0]; j = np.where((lon >= W) & (lon <= E))[0]
    if not len(i) or not len(j): raise RuntimeError("برش خالی: bbox بیرون از شبکه")
    a = np.array(pre[:, i[0]:i[-1] + 1, j[0]:j[-1] + 1], dtype="float32"); close()
    a[(a < 0) | (a < -900)] = np.nan; la, lo = lat[i], lon[j]
    if la[0] > la[-1]: a = a[:, ::-1]; la = la[::-1]
    return a, la, lo

def get_year(y, bbox, cache, mock=False):
    """بارش روزانهٔ سال y: (days, nlat, nlon) float32 با NaN برای نبود داده + lat + lon. در cache به‌صورت int16 (×۱۰) نگه می‌دارد."""
    S, N, W, E = bbox; f = os.path.join(cache, f"chirps_{y}_{S}_{N}_{W}_{E}.npz")
    if os.path.exists(f):
        z = np.load(f); a = z["a"].astype("float32") / 10.0; a[z["a"] == NODATA] = np.nan; return a, z["lat"], z["lon"]
    if mock: raise RuntimeError("mock: cache پر نشده")
    import tempfile
    os.makedirs(cache, exist_ok=True)
    if SRCDIR:
        a, la, lo = _read_nc(os.path.join(SRCDIR, f"chirps-v2.0.{y}.days_p25.nc"), bbox)
    else:
        import requests
        tmp = tempfile.NamedTemporaryFile(suffix=".nc", delete=False); tmp.close()
        try:
            for k in range(4):
                try:
                    with requests.get(URL.format(y=y), stream=True, timeout=120) as r:
                        r.raise_for_status()
                        with open(tmp.name, "wb") as o:
                            for ch in r.iter_content(1 << 22): o.write(ch)
                    break
                except Exception as e:
                    log(f"  … {y}: {e}"); time.sleep(8 * (k + 1))
            else: raise RuntimeError(f"دانلود {y} شکست خورد")
            a, la, lo = _read_nc(tmp.name, bbox)
        finally:
            try: os.unlink(tmp.name)
            except OSError: pass
    q = np.where(np.isnan(a), NODATA, np.round(a * 10)).astype("int16")
    np.savez_compressed(f, a=q, lat=la, lon=lo); log(f"  ✓ {y}: {a.shape}")
    return a, la, lo

def water_year(prev, nxt, y0):
    """از دادهٔ سال y0 و y0+1 → (365, nlat*nlon) از ۱ اوت تا ۳۱ ژوئیه؛ ۲۹ فوریه حذف."""
    d0 = dt.date(y0, 8, 1); i0 = (d0 - dt.date(y0, 1, 1)).days
    a = np.concatenate([prev[i0:], nxt[: (dt.date(y0 + 1, 8, 1) - dt.date(y0 + 1, 1, 1)).days]], axis=0)
    a = OM.water_year_array(a.reshape(a.shape[0], -1), y0); return a

def build(args):
    S, N, W, E = [float(x) for x in args.bbox.split(",")]; bbox = (S, N, W, E); y0, y1 = [int(x) for x in args.years.split("-")]   # سال آغاز سال آبی
    meths = [m for m in args.methods.split(",") if m in OM.METHODS]
    cache = args.cache; data = {}
    def need(y):
        if y not in data: data[y] = get_year(y, bbox, cache, args.mock)
        return data[y]
    lat = lon = None; res = {m: np.full((2, y1 - y0 + 1, 0), -1, dtype=np.int16) for m in meths}
    # گذر ۱: میانگین بلندمدت بارش روزانه (آستانهٔ روش ایرانی)
    ssum = 0; scnt = 0
    for y in range(y0, y1 + 1):
        try: a, la, lo = need(y); need(y + 1)
        except Exception as e: log(f"✗ سال {y}: {e}"); sys.exit(2)
        lat, lon = la, lo; w = water_year(data[y][0], data[y + 1][0], y); ssum = ssum + np.nan_to_num(w).sum(axis=0); scnt = scnt + (~np.isnan(w)).sum(axis=0)
        for k in [k for k in data if k < y]: data.pop(k)       # فقط دو سال در حافظه
    thr = ssum / np.maximum(scnt, 1); n = thr.size
    out = {m: np.full((2, y1 - y0 + 1, n), -1, dtype=np.int16) for m in meths}
    for y in range(y0, y1 + 1):
        w = water_year(need(y)[0], need(y + 1)[0], y); t0 = time.time()
        for m in meths:
            f = OM.METHODS[m][0]; o, c = (f(w, None, thr) if m == "irn" else f(w))
            out[m][0, y - y0], out[m][1, y - y0] = o, c
        log(f"✓ سال آبی {y}/{y + 1} ({time.time() - t0:.1f}s)")
        for k in [k for k in data if k < y]: data.pop(k)
    return out, lat, lon, y0, y1, thr

def save(out, lat, lon, y0, y1, thr, region, outdir, args):
    os.makedirs(outdir, exist_ok=True); order = list(out)
    arr = np.stack([out[m] for m in order]).reshape(len(order), 2, y1 - y0 + 1, len(lat), len(lon))
    buf = gzip.compress(arr.astype("<i2").tobytes(), 9)
    dlat = float(lat[1] - lat[0]) if len(lat) > 1 else 0.25; dlon = float(lon[1] - lon[0]) if len(lon) > 1 else 0.25
    meta = {"v": 1, "region": region, "nlat": len(lat), "nlon": len(lon), "lat0": float(lat[0]), "lon0": float(lon[0]), "dlat": dlat, "dlon": dlon, "y0": y0, "ny": y1 - y0 + 1,
            "T": OM.T, "day0": "08-01", "src": "CHIRPS v2.0 daily p25 (UCSB CHC)", "built": dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ"), "mock": bool(args.mock),
            "methods": [{"id": m, "fa": OM.METHODS[m][1], "en": OM.METHODS[m][2], "onset": OM.METHODS[m][3], "cess": OM.METHODS[m][4], "params": OM.PARAMS.get(m, {})} for m in order],
            "note": "day = شمارندهٔ روز از ۱ اوت (۲۹ فوریه حذف)؛ -1 = تعریف نشد"}
    jp = os.path.join(outdir, f"onset_{region}.json"); bp = os.path.join(outdir, f"onset_{region}.bin")
    open(jp, "w", encoding="utf-8").write(json.dumps(meta, ensure_ascii=False, separators=(",", ":"))); open(bp, "wb").write(buf)
    log(f"✓ ذخیره: {jp} ({os.path.getsize(jp)} B)، {bp} ({len(buf) / 1e6:.2f} MB)"); return jp, bp

def upload(outdir, region, host, key):
    import requests
    for nm in (f"onset_{region}.json", f"onset_{region}.bin"):
        p = os.path.join(outdir, nm); u = f"{host.rstrip('/')}/nwp_upload.php?a=onsetput"
        for k in range(4):
            try:
                r = requests.post(u, data={"name": nm, "key": key}, files={"f": (nm, open(p, "rb"))}, timeout=180)
                if r.status_code == 403: sys.exit("✗ کلید آپلود اشتباه است")
                if r.json().get("ok"): log(f"✓ ارسال {nm}"); break
                log(f"  ✗ {nm}: {r.text[:120]}")
            except SystemExit: raise
            except Exception as e: log(f"  … {e}"); time.sleep(5 * (k + 1))
        else: sys.exit(f"✗ ارسال {nm} شکست خورد")

def make_mock(cache, bbox, y0, y1):
    """داده ساختگی (بدون شبکه): سه‌گانهٔ شمال‌غرب مرطوب‌تر و زودتر؛ جنوب‌شرق خشک و دیرتر. فقط برای آزمون کد."""
    S, N, W, E = bbox; lat = np.arange(S, N + .01, .25); lon = np.arange(W, E + .01, .25); rng = np.random.default_rng(7); os.makedirs(cache, exist_ok=True)
    for y in range(y0, y1 + 2):
        nd = 366 if (y % 4 == 0) else 365; a = np.zeros((nd, len(lat), len(lon)), dtype="float32"); doy = np.arange(nd)[:, None, None]
        gx = (lon[None, None, :] - W) / (E - W); gy = (lat[None, :, None] - S) / (N - S); on = 300 + 40 * (1 - gy) - 25 * gy + rng.normal(0, 12); en = 120 + 15 * gy + rng.normal(0, 8)
        # فصل: از اواخر مهر (روز ~۳۰۰) تا اردیبهشت (روز ~۱۲۰ سال بعد)؛ ساده: دو بخش در سال تقویمی
        season = ((doy >= on) | (doy <= en)).astype("float32"); pw = 0.08 + 0.3 * gy * season; rain = (rng.random(a.shape) < pw) * rng.gamma(.7, 9, a.shape)
        a = (rain * (0.4 + gy)).astype("float32"); q = np.round(a * 10).astype("int16")
        np.savez_compressed(os.path.join(cache, f"chirps_{y}_{S}_{N}_{W}_{E}.npz"), a=q, lat=lat, lon=lon)

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--list", action="store_true"); ap.add_argument("--region", default="iran"); ap.add_argument("--bbox", default="24,41,43,64")
    ap.add_argument("--years", default="1981-2024", help="سال آغاز سال آبی: از-تا"); ap.add_argument("--methods", default="siv,cam,mor,fer,cum,irn"); ap.add_argument("--cache", default="chirps_cache")
    ap.add_argument("--out", default="out"); ap.add_argument("--mock", action="store_true"); ap.add_argument("--host"); ap.add_argument("--key"); ap.add_argument("--upload", action="store_true"); ap.add_argument("--srcdir", help="آزمون: پوشهٔ فایل‌های .nc محلی")
    a = ap.parse_args()
    global SRCDIR; SRCDIR = a.srcdir
    if a.list:
        import requests; t = requests.get(LIST_URL, timeout=60).text; ys = sorted(set(re.findall(r"chirps-v2\.0\.(\d{4})\.days_p25\.nc", t))); log("سال‌های موجود:", ys[0], "تا", ys[-1], f"({len(ys)} فایل)"); return
    if a.upload:
        if not (a.host and a.key): sys.exit("--host و --key لازم است")
        upload(a.out, a.region, a.host, a.key); return
    if a.mock:
        y0, y1 = [int(x) for x in a.years.split("-")]; make_mock(a.cache, tuple(float(x) for x in a.bbox.split(",")), y0, y1)
    out, lat, lon, y0, y1, thr = build(a); save(out, lat, lon, y0, y1, thr, a.region, a.out, a)

if __name__ == "__main__": main()

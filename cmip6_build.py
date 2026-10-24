#!/usr/bin/env python3
"""ساخت دادهٔ پیش‌نگری CMIP6 ایران (شبکهٔ ۲°) از Copernicus CDS ← cmip6_iran.json (+ ارسال به هاست).
مخزن: metstat-site (خصوصی؛ Secret: CDSAPI_KEY). پیش‌نیاز: pip install cdsapi xarray netCDF4 cftime numpy scipy requests

حالت‌ها:
  --probe  [--models a,b]      : برای هر مدل/سناریو/متغیر یک درخواست کوچک (۱ سال) می‌فرستد و می‌نویسد کدام در دسترس است (اول این را اجرا کن)
  --model X --part out.npz     : دانلود و پردازش یک مدل (همهٔ سناریوها) → فایل part (برای ماتریس workflow)
  --merge parts/ --out f.json  : ادغام partها → cmip6_iran.json
  --upload f.json --host H --key K : ارسال به هاست (nwp_upload.php نسخهٔ r55)
  --mock --out f.json          : بدون شبکه با دادهٔ ساختگی (فقط آزمون ساختار؛ دادهٔ علمی نیست)
نکته: نام مدل‌ها و کلیدهای درخواست CDS از حافظه است و از این‌جا آزموده نشد؛ --probe خطای دقیق را چاپ می‌کند.
"""
import argparse, glob, json, os, sys, time, zipfile, tempfile, datetime
import numpy as np
import cmip6_core as C

MODELS = ["access_cm2", "canesm5", "cnrm_cm6_1", "ec_earth3", "gfdl_esm4", "inm_cm5_0", "ipsl_cm6a_lr", "miroc6", "mpi_esm1_2_lr", "mri_esm2_0", "noresm2_mm", "ukesm1_0_ll"]
EXPS = {"historical": C.HIST, "ssp1_2_6": C.FUT, "ssp2_4_5": C.FUT, "ssp3_7_0": C.FUT, "ssp5_8_5": C.FUT}
SCEN_KEY = {"ssp1_2_6": "ssp126", "ssp2_4_5": "ssp245", "ssp3_7_0": "ssp370", "ssp5_8_5": "ssp585"}
VARS = {"tas": "near_surface_air_temperature", "pr": "precipitation"}
AREA = [42, 40, 22, 66]          # N W S E (کمی بزرگ‌تر از شبکهٔ ۲۴–۴۰°N، ۴۲–۶۴°E تا درون‌یابی دوخطی لبه‌ها را بپوشاند)

def request_variants(model, exp, var, years):
    base = {"temporal_resolution": "monthly", "experiment": exp, "variable": VARS[var], "model": model,
            "year": [str(y) for y in years], "month": [f"{m:02d}" for m in range(1, 13)], "area": AREA}
    yield {**base, "data_format": "netcdf", "download_format": "zip"}
    yield {**base, "format": "zip"}
    yield {**base, "level": "single_levels", "data_format": "netcdf", "download_format": "zip"}
    yield {**base, "level": "single_levels", "format": "zip"}

def retrieve(client, model, exp, var, years, workdir, log):
    """یک درخواست؛ چند شکل کلید را به‌ترتیب امتحان می‌کند. خروجی: فهرست فایل‌های nc یا None."""
    last = None
    for req in request_variants(model, exp, var, years):
        tgt = os.path.join(workdir, f"{model}_{exp}_{var}.zip")
        try:
            client.retrieve("projections-cmip6", req, tgt)
            d = os.path.join(workdir, f"{model}_{exp}_{var}"); os.makedirs(d, exist_ok=True)
            if zipfile.is_zipfile(tgt):
                with zipfile.ZipFile(tgt) as z: z.extractall(d)
            else: os.replace(tgt, os.path.join(d, "x.nc"))
            fs = sorted(glob.glob(os.path.join(d, "**", "*.nc"), recursive=True)); return fs
        except Exception as e:
            last = str(e).strip().splitlines()[-1][:300] if str(e).strip() else repr(e)
            log(f"    ✗ {model}/{exp}/{var} شکل درخواست {list(req)[-2:]}: {last}")
            if "not found" in last.lower() or "no data" in last.lower() or "500" in last: break      # فرق نمی‌کند شکل را عوض کنیم
    return None

def read_nc(path, var):
    """خواندن NetCDF → dict(lat, lon, years, months, data[t,y,x]). فقط این تابع به xarray وابسته است (آزموده‌نشده از سندباکس)."""
    import xarray as xr
    ds = xr.open_dataset(path, use_cftime=True)
    name = {"tas": "tas", "pr": "pr"}[var]
    if name not in ds: raise KeyError(f"{name} در {os.path.basename(path)} نیست؛ متغیرها: {list(ds.data_vars)}")
    da = ds[name]
    if "member" in da.dims or "realization" in da.dims: da = da.isel({d: 0 for d in da.dims if d in ("member", "realization")})
    lat = ds["lat"].values if "lat" in ds else ds["latitude"].values; lon = ds["lon"].values if "lon" in ds else ds["longitude"].values
    return {"lat": lat, "lon": lon, "years": np.array([t.year for t in ds["time"].values]), "months": np.array([t.month for t in ds["time"].values]), "data": np.asarray(da.values).reshape(len(ds["time"]), len(lat), len(lon))}

def build_model(model, client, workdir, log):
    out = {"model": model, "tas": {}, "pr": {}, "seas": {}, "missing": []}
    for exp, years in EXPS.items():
        key = "hist" if exp == "historical" else SCEN_KEY[exp]
        for var in VARS:
            fs = retrieve(client, model, exp, var, range(years[0], years[1] + 1), workdir, log)
            if not fs: out["missing"].append(f"{exp}/{var}"); continue
            try:
                r = read_nc(fs[0], var); ann, seas = C.process_exp(var, r["data"], r["lat"], r["lon"], r["years"], r["months"], exp)
                out[var][key] = C.pack(ann, var); out["seas"][f"{var}_{key}"] = C.pack(seas, var); log(f"  ✓ {model} {exp} {var}")
            except Exception as e: out["missing"].append(f"{exp}/{var}"); log(f"  ✗ پردازش {model} {exp} {var}: {e}")
    return out

def save_part(o, path):
    np.savez_compressed(path, model=o["model"], missing=json.dumps(o["missing"]), **{f"{v}|{k}": a for v in ("tas", "pr") for k, a in o[v].items()}, **{f"seas|{k}": a for k, a in o["seas"].items()})
def load_part(path):
    z = np.load(path, allow_pickle=False); o = {"model": str(z["model"]), "tas": {}, "pr": {}, "seas": {}, "missing": json.loads(str(z["missing"]))}
    for k in z.files:
        if "|" not in k: continue
        a, b = k.split("|", 1); (o["seas"] if a == "seas" else o[a])[b] = z[k]
    return o

def merge(parts, meta=None):
    parts = [p for p in parts if p["tas"].get("hist") is not None and p["pr"].get("hist") is not None and any(k in p["tas"] for k in SCEN_KEY.values())]
    if not parts: raise SystemExit("✗ هیچ مدلی دادهٔ کامل ندارد")
    J = {"v": 1, "grid": {"lat0": float(C.GRID_LAT[0]), "dlat": 2.0, "nlat": len(C.GRID_LAT), "lon0": float(C.GRID_LON[0]), "dlon": 2.0, "nlon": len(C.GRID_LON)},
         "hist": list(C.HIST), "fut": list(C.FUT), "base": list(C.BASE), "windows": [list(w) for w in C.WINDOWS], "seasons": list(C.SEASONS), "scale": C.SCALE,
         "scen": list(SCEN_KEY.values()), "models": [p["model"] for p in parts], "tas": {}, "pr": {}, "seas": {}, "missing": {p["model"]: p["missing"] for p in parts if p["missing"]},
         "meta": {"built": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ"), "source": "Copernicus CDS projections-cmip6 (monthly); first available ensemble member", "note": "regridded bilinearly to 2°; annual means; seasonal 20-yr window means"}}
    if meta: J["meta"].update(meta)
    for p in parts:
        for v in ("tas", "pr"):
            J[v][p["model"]] = {k: C.b64(a) for k, a in p[v].items()}
        J["seas"][p["model"]] = {k: C.b64(a) for k, a in p["seas"].items()}
    return J

def mock_part(model, seed):
    """ساختگی: دمای پایه + روند وابسته به سناریو + نوسان؛ فقط برای آزمون ساختار."""
    rng = np.random.default_rng(seed); lat = np.arange(42, 22 - 0.1, -1.875); lon = np.arange(40, 66 + 0.1, 1.875); LA, LO = np.meshgrid(lat, lon, indexing="ij"); sens = rng.uniform(0.8, 1.4)
    out = {"model": model, "tas": {}, "pr": {}, "seas": {}, "missing": []}
    for exp, (y0, y1) in EXPS.items():
        key = "hist" if exp == "historical" else SCEN_KEY[exp]; yrs = np.repeat(np.arange(y0, y1 + 1), 12); mos = np.tile(np.arange(1, 13), y1 - y0 + 1)
        rate = {"historical": 0.012, "ssp1_2_6": 0.018, "ssp2_4_5": 0.030, "ssp3_7_0": 0.045, "ssp5_8_5": 0.060}[exp] * sens; t0 = 1995 if exp == "historical" else 2015
        for var in VARS:
            if var == "tas":
                d = 273.15 + (17 - 0.5 * (LA - 32)[None] - 12 * np.cos((mos - 1)[:, None, None] / 12 * 2 * np.pi)) + rate * (yrs - 1995)[:, None, None] + rng.normal(0, 0.4, (len(yrs), 1, 1))
            else:
                d = np.clip(1.2e-5 * (1 + 0.6 * np.cos((mos - 1)[:, None, None] / 12 * 2 * np.pi)) * (1 + 0.02 * rate / 0.03 * (yrs - 1995)[:, None, None] * rng.choice([-1, 1]) / 20) * (0.8 + 0.4 * (LA / 40)[None]), 0, None) * (1 + rng.normal(0, 0.1, (len(yrs), 1, 1)))
            ann, sw = C.process_exp(var, d, lat, lon, yrs, mos, exp); out[var][key] = C.pack(ann, var); out["seas"][f"{var}_{key}"] = C.pack(sw, var)
    return out

def upload(path, host, key):
    import requests
    with open(path, "rb") as f:
        r = requests.post(f'{host.rstrip("/")}/nwp_upload.php?a=cmipput&key={requests.utils.quote(key)}', data={"name": os.path.basename(path)}, files={"f": (os.path.basename(path), f, "application/json")}, timeout=300)
    print("upload:", r.status_code, r.text[:200]); r.raise_for_status()

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--probe", action="store_true"); ap.add_argument("--models", default=",".join(MODELS)); ap.add_argument("--model"); ap.add_argument("--part")
    ap.add_argument("--merge"); ap.add_argument("--out", default="cmip6_iran.json"); ap.add_argument("--upload"); ap.add_argument("--host"); ap.add_argument("--key"); ap.add_argument("--mock", action="store_true"); a = ap.parse_args()
    log = lambda s: print(s, flush=True)
    if a.mock:
        ms = a.models.split(","); J = merge([mock_part(m, i) for i, m in enumerate(ms)], {"mock": True, "note": "MOCK — ساختگی، دادهٔ علمی نیست"}); json.dump(J, open(a.out, "w"), separators=(",", ":")); print("mock →", a.out, os.path.getsize(a.out) // 1024, "KB"); return
    if a.upload: upload(a.upload, a.host, a.key); return
    if a.merge:
        parts = [load_part(f) for f in sorted(glob.glob(os.path.join(a.merge, "**", "*.npz"), recursive=True))]; J = merge(parts); json.dump(J, open(a.out, "w"), separators=(",", ":")); print("merged", len(J["models"]), "models →", a.out, os.path.getsize(a.out) // 1024, "KB; ناقص:", J["missing"]); return
    import cdsapi; client = cdsapi.Client(quiet=True, retry_max=2, sleep_max=20, timeout=120)   # پیش‌فرض cdsapi روی خطای ۵۰۰ تا ۵۰۰ بار×۱۲۰ث تکرار می‌کند؛ این‌جا فقط ۲ بار
    if a.probe:
        import time as _t; T0 = _t.time(); ok_n = 0; tot = 0
        with tempfile.TemporaryDirectory() as wd:
            for m in a.models.split(","):
                for exp in EXPS:
                    for var in VARS:
                        if _t.time() - T0 > 40 * 60: log("⏹ سقف ۴۰ دقیقه"); log(f"\nخلاصه: {ok_n}/{tot} ترکیب در دسترس"); return
                        tot += 1; y = C.HIST[1] if exp == "historical" else C.FUT[0]; fs = retrieve(client, m, exp, var, [y], wd, log); ok = bool(fs); ok_n += ok; log(f"{'✓' if ok else '✗'} {m:16s} {exp:11s} {var}")
        log(f"\nخلاصه: {ok_n}/{tot} ترکیب در دسترس"); return
    if not a.model or not a.part: ap.error("--model و --part لازم است")
    with tempfile.TemporaryDirectory() as wd: o = build_model(a.model, client, wd, log)
    save_part(o, a.part); log(f"part → {a.part} (ناقص: {o['missing']})")
if __name__ == "__main__": main()

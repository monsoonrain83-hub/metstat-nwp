#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
xro_forecast.py — پیش‌بینی ماهانهٔ شاخص‌های اقلیمی با مدل XRO (Zhao و همکاران، Nature 2024)
  XRO = «Extended nonlinear Recharge Oscillator» — مدل آماری-پویای سبک که با نوفهٔ تصادفی گروه پیش‌بینی می‌سازد.
  مقاله : Zhao, S., Jin, F.-F., Long, X. et al. (2024) Nature, https://doi.org/10.1038/s41586-024-07534-6
  کد    : https://github.com/senclimate/XRO  (CC-BY-4.0)  ·  داده/نسخهٔ آرشیو: Zenodo 10.5281/zenodo.10681114
⚠ این اسکریپت در محیط توسعه نصب‌شدنیِ XRO نداشت و فقط از روی مستندات نوشته شده است. حالت --probe همهٔ فرض‌ها (نام متغیرها، امضای توابع)
  را چاپ و یک بازپیش‌بینی آزمایشی با امتیاز مهارت می‌دهد؛ پیش از اعتماد به خروجی، یک بار --probe را در GitHub اجرا و بخوانید.
⚠ حالت اولیه: وضعیت اولیه = آخرین ماهِ فایل شاخص‌های ORAS5 (indices_oras5.nc). اگر این فایل به‌روز نباشد، پیش‌بینی از آن ماه شروع می‌شود
  (در خروجی و روی نمودار «آغاز پیش‌بینی» نوشته می‌شود). به‌روزرسانی بی‌درنگ وضعیت اولیه (WWV از ORAS5/CDS) هنوز پیاده نشده است.
خروجی: <id>.json (kind=plume، سازگار با نمودار سایت) + PNG؛ آپلود با nwp_upload.php?a=idxput
"""
import argparse, io, json, os, sys, datetime as dt, inspect
import numpy as np

CITE = "Zhao et al. 2024, Nature, doi:10.1038/s41586-024-07534-6; code doi:10.5281/zenodo.10681114 (CC-BY-4.0)"
# شاخص‌های خروجی: متغیر XRO → (id سایت، نام فارسی، انگلیسی، آستانهٔ فاز)
OUT = {"Nino34": ("nino34_xro", "نینو ۳٫۴", "Niño 3.4", 0.5),
       "IOD":    ("dmi_xro",    "دوقطبی اقیانوس هند (IOD)", "Indian Ocean Dipole (IOD)", 0.4)}
def log(*a): print(*a, flush=True)

def load_ds(path):
    import xarray as xr
    ds = xr.open_dataset(path)
    log("متغیرها:", list(ds.data_vars), "| زمان:", str(ds.time.values[0])[:7], "→", str(ds.time.values[-1])[:7])
    return ds

def pick(ds, names):
    for n in names:
        if n in ds: return n
    return None

def probe(ds, a):
    import XRO, xarray as xr
    from XRO.core import XRO as XROc
    log("XRO نسخه:", getattr(XRO, "__version__", "?"))
    for fn in ("fit_matrix", "simulate", "reforecast", "get_RO_parameters"):
        if hasattr(XROc, fn): log(f"  {fn}{inspect.signature(getattr(XROc, fn))}")
        else: log(f"  ✗ {fn} وجود ندارد")
    log("پارامترهای __init__:", inspect.signature(XROc.__init__))

def fit_model(ds, a):
    from XRO.core import XRO as XROc
    train = ds.sel(time=slice(a.train0, a.train1))
    vars_ = [v for v in a.vars.split(",") if v in train]
    if "Nino34" not in vars_: sys.exit("✗ Nino34 در دادهٔ آموزش نیست")
    train = train[vars_]
    m = XROc(ncycle=12, ac_order=a.ac)
    fit = m.fit_matrix(train, maskb=[], maskNT=[])
    return m, fit, train

def forecast(m, fit, init_ds, a):
    """ بازپیش‌بینی گروهی از وضعیت اولیه؛ خروجی xarray با ابعاد (member, time|lead, ...) بسته به نسخهٔ XRO """
    try:
        return m.reforecast(fit_ds=fit, init_ds=init_ds, n_month=a.months, ncopy=a.members, noise_type="red")
    except TypeError as e:
        log("reforecast با نام‌های بالا کار نکرد:", e); raise

def to_arrays(fc, var):
    """ → آرایهٔ (member, lead) برای یک متغیر؛ بعدها را بر اساس نامشان حدس می‌زند و در لاگ می‌نویسد """
    x = fc[var]; log(f"  شکل {var}:", dict(zip(x.dims, x.shape)))
    dims = list(x.dims)
    mem = next((d for d in dims if d in ("member", "ncopy", "copy", "ens")), None)
    lead = next((d for d in dims if d in ("lead", "time", "step", "n_month")), None)
    init = next((d for d in dims if d in ("init", "init_time", "start")), None)
    if init and x.sizes[init] > 1: x = x.isel({init: -1})
    elif init: x = x.isel({init: 0})
    if mem is None or lead is None: sys.exit(f"✗ ابعاد ناشناخته {dims}؛ --probe را اجرا و خروجی را بفرستید")
    return np.asarray(x.transpose(mem, lead).values, float)

def skill_test(ds, a):
    """ آزمون مهارت: بازپیش‌بینی برای ۱۲ سال آخر با آموزش روی پیش از آن (فقط نینو ۳٫۴؛ همبستگی میانگین گروه با مشاهده در هر پیشرو) """
    from XRO.core import XRO as XROc
    t_end = str(ds.time.values[-1])[:4]; split = int(t_end) - 12
    m, fit, train = fit_model(ds, argparse.Namespace(**{**vars(a), "train1": f"{split}-12"}))
    obs = ds["Nino34"]; rs = {}
    for lead in (3, 6, 9, 12):
        P, O = [], []
        for y in range(split + 1, int(t_end)):
            for mo in (1, 4, 7, 10):
                t0 = f"{y}-{mo:02d}"
                try:
                    init = ds[list(train.data_vars)].sel(time=slice(t0, t0))
                    fc = forecast(m, fit, init, argparse.Namespace(**{**vars(a), "months": lead, "members": 20}))
                    arr = to_arrays(fc, "Nino34"); P.append(arr[:, lead].mean() if arr.shape[1] > lead else np.nan)
                    k = (y * 12 + mo - 1 + lead); O.append(float(obs.sel(time=f"{k//12}-{k%12+1:02d}").values[0]))
                except Exception as e:
                    log("  ✗", t0, lead, str(e)[:100]); break
        if len(P) > 5: rs[lead] = float(np.corrcoef(P, O)[0, 1])
    log("امتیاز مهارت (همبستگی میانگین گروه با مشاهده، نینو ۳٫۴):", rs)
    return rs

def month_days(y, m): return (dt.date(y + (m == 12), m % 12 + 1, 1) - dt.date(y, m, 1)).days

def build_ser(ds, var, mem, thr, a, init_date, obs=None):
    """ ساخت JSON نمودار (kind=plume): obs ماهانه (به شکل روز ۱۵ هر ماه) + گروه پیش‌بینی با پیشروی به روز نسبت به init """
    if obs is not None:
        mm, vv = obs; ok = [i for i, x in enumerate(vv) if np.isfinite(x) and mm[i] <= init_date.strftime("%Y-%m")][-a.hist:]
        ot = [mm[i] + "-15" for i in ok]; ov = [float(vv[i]) for i in ok]
    else:
        o = ds[var].dropna("time").isel(time=slice(-a.hist, None)); ot = [str(t)[:7] + "-15" for t in o.time.values]; ov = [float(x) for x in o.values]
    n = mem.shape[1]; lead = []; labs = []
    y, m = init_date.year, init_date.month
    for k in range(n):
        yy, mm = y + (m - 1 + k) // 12, (m - 1 + k) % 12 + 1; mid = dt.date(yy, mm, 15); lead.append((mid - init_date).days); labs.append(f"{yy}-{mm:02d}")
    ser = {"kind": "plume", "obs": {"t": ot, "v": [round(float(v), 3) for v in ov]},
           "fc": {"init": init_date.isoformat(), "lead": lead, "mem": [[round(float(x), 3) for x in r] for r in mem[:a.show]], "mean": [round(float(x), 3) for x in mem.mean(0)]},
           "cite": CITE}
    summ = [{"l": labs[k], "v": float(mem[:, k].mean()), "lo": float(np.quantile(mem[:, k], .1)), "hi": float(np.quantile(mem[:, k], .9)),
             "pp": float((mem[:, k] > thr).mean() * 100), "pn": float((mem[:, k] < -thr).mean() * 100)} for k in range(0, n, max(1, n // 8))][:12]
    return ser, summ, labs

def render_png(ser, title, thr):
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    O = ser["obs"]; F = ser["fc"]; init = dt.date.fromisoformat(F["init"])
    ot = [dt.date.fromisoformat(t) for t in O["t"]]; ft = [init + dt.timedelta(days=l) for l in F["lead"]]
    fig, ax = plt.subplots(figsize=(9, 4.6), dpi=130)
    ax.bar(ot, O["v"], width=24, color=["#dc2626" if v >= thr else "#2563eb" if v <= -thr else "#94a3b8" for v in O["v"]])
    M = np.array(F["mem"]); [ax.plot(ft, r, color="#7c3aed", alpha=.22, lw=.8) for r in M]
    ax.fill_between(ft, np.quantile(M, .1, 0), np.quantile(M, .9, 0), color="#7c3aed", alpha=.2); ax.plot(ft, F["mean"], color="#6d28d9", lw=2.6)
    for s in (thr, -thr): ax.axhline(s, color="#64748b", ls="--", lw=1)
    ax.axvline(init, color="#6d28d9", ls=":"); ax.set_title(title, fontsize=13, fontweight="bold"); ax.grid(alpha=.25)
    ax.set_xlabel("XRO forecast · init " + F["init"] + " · " + CITE[:42] + "…", fontsize=8); fig.tight_layout(); b = io.BytesIO(); fig.savefig(b, format="png"); plt.close(fig); return b.getvalue()

def post(a, iid, png, meta, ser, requests):
    u = f'{a.host.rstrip("/")}/nwp_upload.php?a=idxput&key={requests.utils.quote(a.key)}'
    for k in range(4):
        try:
            r = requests.post(u, data=dict(id=iid, per="fc", meta=json.dumps(meta)), files={"png": (f"{iid}_fc.png", png, "image/png"), "ser": (f"{iid}.json", json.dumps(ser).encode(), "application/json")}, timeout=90)
            if r.status_code == 403: sys.exit("✗ کلید آپلود اشتباه است")
            if r.json().get("ok"): return True
            log("  ✗ پاسخ هاست:", r.text[:120])
        except SystemExit: raise
        except Exception as e: log("  ✗", e)
    return False

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="مسیر indices_oras5.nc (یا هر فایل شاخص با متغیرهای Nino34, WWV, ...)")
    ap.add_argument("--probe", action="store_true"); ap.add_argument("--skill", action="store_true")
    ap.add_argument("--train0", default="1979-01"); ap.add_argument("--train1", default=None); ap.add_argument("--vars", default="Nino34,WWV,NPMM,SPMM,IOD,SIOD,TNA,ATL3,SASD")
    ap.add_argument("--ac", type=int, default=2); ap.add_argument("--months", type=int, default=21); ap.add_argument("--members", type=int, default=100); ap.add_argument("--show", type=int, default=40)
    ap.add_argument("--hist", type=int, default=36); ap.add_argument("--max-age", type=int, default=3, help="حداکثر عمر وضعیت اولیه (ماه) برای آپلود"); ap.add_argument("--allow-stale", action="store_true")
    ap.add_argument("--realtime", action="store_true", help="وضعیت اولیهٔ به‌روز از ERSST (+WWV از ORAS5 با --wwv)"); ap.add_argument("--wwv", action="store_true")
    ap.add_argument("--z20-from", default="2005-01"); ap.add_argument("--z20-cache", default="wwv_z20.json"); ap.add_argument("--min-r", type=float, default=0.85); ap.add_argument("--min-init", default=None); ap.add_argument("--ersst", default=None); ap.add_argument("--host"); ap.add_argument("--key"); ap.add_argument("--out")
    a = ap.parse_args(); ds = load_ds(a.data)
    a.train1 = a.train1 or str(ds.time.values[-1])[:7]
    if a.probe: probe(ds, a)
    if a.skill: skill_test(ds, a)
    if a.probe or a.skill:
        if not a.host and not a.out: return
    obs_over = {}
    if a.realtime:
        import xro_realtime as RT, xarray as xr
        vals, im, hist, rep = RT.build_state(ds, a, a.ersst); [log("  ", r) for r in rep]; log("وضعیت اولیهٔ به‌روز:", im, {k: round(v, 2) for k, v in vals.items()})
        a.vars = ",".join(k for k in a.vars.split(",") if k in vals); log("متغیرهای مدل:", a.vars)
        m, fit, train = fit_model(ds, a); init_date = dt.date(int(im[:4]), int(im[5:7]), 1)
        init = xr.Dataset({k: ("time", [vals[k]]) for k in train.data_vars}, coords={"time": [np.datetime64(f"{im}-01")]}); obs_over = {k: hist[k] for k in hist}
    else:
        m, fit, train = fit_model(ds, a); last = ds.time.values[-1]; init_date = dt.date(int(str(last)[:4]), int(str(last)[5:7]), 1)
        init = ds[list(train.data_vars)].sel(time=slice(str(last)[:7], str(last)[:7]))
    age = (dt.date.today().year - init_date.year) * 12 + dt.date.today().month - init_date.month
    log("آغاز پیش‌بینی از:", init_date, f"(عمر وضعیت اولیه {age} ماه)")
    if a.host and age > a.max_age and not a.allow_stale: sys.exit(f"✗ وضعیت اولیه {age} ماه قدیمی است؛ آپلود نشد تا پیش‌بینیِ کهنه در سایت نیاید. (وضعیت اولیهٔ به‌روز باید ساخته شود؛ یا --allow-stale)")
    fc = forecast(m, fit, init, a); import requests
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d"); ok = 0
    for var, (iid, fa, en, thr) in OUT.items():
        if var not in fc: log("✗ در خروجی XRO نیست:", var); continue
        mem = to_arrays(fc, var); ser, summ, labs = build_ser(ds, var, mem, thr, a, init_date, obs_over.get(var))
        meta = dict(fa=fa + " — XRO", en=en + " · XRO", grp="XRO", src="XRO model (Zhao et al. 2024, Nature) · trained on ORAS5 indices · run by MetStat", last=init_date.isoformat(), upd=now, unit="°C", kind="plume", mdl="xro", fc=summ,
                    note="XRO: گروه ۱۰۰ عضوی از شبیه‌سازی نوفه‌دار مدل نوسان‌گر شارژ مجدد؛ آغاز پیش‌بینی = آخرین ماه فایل شاخص‌ها. " + CITE)
        png = render_png(ser, f"{en} — XRO ensemble forecast", thr)
        if a.out: os.makedirs(a.out, exist_ok=True); open(os.path.join(a.out, f"{iid}.json"), "w").write(json.dumps(ser)); open(os.path.join(a.out, f"{iid}_fc.png"), "wb").write(png)
        if a.host and post(a, iid, png, dict(meta, perfa="پیش‌بینی گروهی ۲۱ ماه"), ser, requests): ok += 1
        log("✓", iid, "پیشرو آخر: میانگین", round(float(mem[:, -1].mean()), 2), "بازهٔ ۱۰–۹۰٪", round(float(np.quantile(mem[:, -1], .1)), 2), round(float(np.quantile(mem[:, -1], .9)), 2))
    if a.host: requests.post(f'{a.host.rstrip("/")}/nwp_upload.php?a=idxend&key={requests.utils.quote(a.key)}', timeout=60)
    if not ok and a.host: sys.exit(1)

if __name__ == "__main__": main()

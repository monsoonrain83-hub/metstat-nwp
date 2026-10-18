#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""شاخص‌های الگوی جوی (NAO، AO، PNA) که MetStat خودش از دادهٔ آزاد ECMWF حساب می‌کند («محاسبهٔ MetStat»؛ رسمی NOAA/ECMWF نیست).
روش (استاندارد و شفاف):
  ۱) یک‌بار (--build-clim): از ERA5 ماهانهٔ ۱۹۹۱–۲۰۲۰ (CDS API؛ نیاز به CDSAPI_KEY) اقلیم ماهانه + الگوی EOF اول هر حوزه + انحراف معیار تصویر ماهانه ساخته و در ecmwf_idx_clim.npz ذخیره می‌شود.
  ۲) هر اجرا: ECMWF open-data ENS (gh در ۵۰۰ و ۱۰۰۰ hPa؛ کنترل + میانگین اعضای آشفته؛ گام ۲۴ ساعته تا ۳۶۰ ساعت) → بی‌هنجاری نسبت به اقلیم → تصویر روی EOF → بی‌مقیاس‌شده → نمودار و سری (kind=plume، mdl=ecmwf).
  تحلیل (گام ۰) روزهای گذشته از فایل سری قبلی روی هاست انباشته می‌شود.
اجرا:  python ecmwf_indices.py --build-clim            (یک‌بار؛ CDSAPI_KEY لازم)
       python ecmwf_indices.py --host H --key K       (روزانه)
       python ecmwf_indices.py --mock --out out       (آزمون بدون شبکه)"""
import argparse, io, json, math, os, sys, datetime as dt
import numpy as np
import indices as IX

CLIM = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ecmwf_idx_clim.npz')
STEPS = list(range(0, 361, 24))
# id: (شناسه، فارسی، انگلیسی، تراز، حوزه (lat0, lat1, lon0, lon1 با lon در −۱۸۰..۱۸۰)، نشانگر علامت (نقطهٔ مثبت، نقطهٔ منفی))
SPEC = {
 'nao': ('nao_ec', 'NAO — پیش‌بینی ECMWF (محاسبهٔ MetStat)', 'NAO', 500, (20, 80, -90, 40), ((38, -30), (65, -20))),
 'ao':  ('ao_ec',  'AO — پیش‌بینی ECMWF (محاسبهٔ MetStat)',  'AO', 1000, (20, 90, -180, 180), ((50, -30), (85, 0))),
 'pna': ('pna_ec', 'PNA — پیش‌بینی ECMWF (محاسبهٔ MetStat)', 'PNA', 500, (20, 85, -180, -60), ((50, -120), (45, -165))),
}
GRP = 'پیش‌بینی ECMWF — محاسبهٔ MetStat'
GRID = 2.5
LATS = np.arange(90, 19.9, -GRID); LONS = np.arange(-180, 180, GRID)
def log(*a): print(*a, flush=True)

# ───────── هستهٔ ریاضی (بدون شبکه؛ قابل آزمون) ─────────
def domain_mask(dom):
    la0, la1, lo0, lo1 = dom; la, lo = np.meshgrid(LATS, LONS, indexing='ij')
    return (la >= la0) & (la <= la1) & (lo >= lo0) & (lo <= lo1)
def weights(): return np.sqrt(np.cos(np.deg2rad(LATS)))[:, None] * np.ones(len(LONS))[None, :]
def climatology_at(clim12, month, day):
    """درون‌یابی دایره‌ای بین میانگین ماهانه (وسط ماه=روز ۱۵)."""
    x = month - 1 + (day - 15) / 30.0; i0 = int(math.floor(x)); f = x - i0
    return (1 - f) * clim12[i0 % 12] + f * clim12[(i0 + 1) % 12]
def build_eof(anom, mask, sign_pts):
    """anom: (زمان, lat, lon) بی‌هنجاری ماهانه. خروجی: الگو (lat, lon، یکه در فضای وزنی)، σ تصویر برای هر ماه."""
    w = weights(); X = (anom * w)[:, mask]; X = X - X.mean(0)
    U, S, Vt = np.linalg.svd(X, full_matrices=False); e = Vt[0]; e = e / np.linalg.norm(e)
    pat = np.zeros(mask.shape); pat[mask] = e
    (pa, pb) = sign_pts; ia = np.unravel_index(np.argmin((LATS[:, None] - pa[0]) ** 2 + (LONS[None, :] - pa[1]) ** 2), mask.shape); ib = np.unravel_index(np.argmin((LATS[:, None] - pb[0]) ** 2 + (LONS[None, :] - pb[1]) ** 2), mask.shape)
    if pat[ia] - pat[ib] < 0: pat = -pat                       # علامت: فاز مثبت = قاعدهٔ رایج
    return pat
def project(field_anom, pat, mask):
    w = weights(); return float(((field_anom * w)[mask] * pat[mask]).sum())
def monthly_sigma(anom, pat, mask, months):
    p = np.array([project(a, pat, mask) for a in anom]); sig = np.array([p[months == m].std() for m in range(1, 13)])
    k = np.array([.25, .5, .25]); ext = np.r_[sig[-1], sig, sig[0]]; return np.convolve(ext, k, 'valid')
def coarsen(a, lat, lon):
    """شبکهٔ ریز (lat کاهشی) → ۲٫۵°: میانگین جعبه‌ای؛ lon به −۱۸۰..۱۸۰."""
    lon = np.where(lon > 180, lon - 360, lon); o = np.argsort(lon); a = a[..., o]; lon = lon[o]
    out = np.full(a.shape[:-2] + (len(LATS), len(LONS)), np.nan)
    for i, la in enumerate(LATS):
        r = (lat >= la - GRID / 2) & (lat < la + GRID / 2) if i else (lat >= la - GRID / 2)
        if not r.any(): continue
        for j, lo in enumerate(LONS):
            c = (lon >= lo - GRID / 2) & (lon < lo + GRID / 2)
            if c.any(): out[..., i, j] = np.nanmean(a[..., r, :][..., :, c], axis=(-2, -1))
    return out
def index_series(Z, dates, clim12, pat, mask, sig12):
    """Z: (زمان, lat, lon) ارتفاع ژئوپتانسیل [m]؛ dates: تاریخ اعتبار → شاخص بی‌مقیاس."""
    out = []
    for z, d in zip(Z, dates):
        an = z - climatology_at(clim12, d.month, d.day)
        x = d.month - 1 + (d.day - 15) / 30.0; i0 = int(math.floor(x)); f = x - i0; sg = (1 - f) * sig12[i0 % 12] + f * sig12[(i0 + 1) % 12]
        out.append(project(np.nan_to_num(an), pat, mask) / sg)
    return np.array(out)

# ───────── ERA5 → اقلیم و EOF (یک‌بار) ─────────
def build_clim(path=CLIM):
    import cdsapi, tempfile
    import xarray as xr
    c = cdsapi.Client(); res = {}
    for lev in sorted({s[3] for s in SPEC.values()}):
        f = os.path.join(tempfile.gettempdir(), f'era5_z{lev}.nc')
        c.retrieve('reanalysis-era5-pressure-levels-monthly-means', {'product_type': 'monthly_averaged_reanalysis', 'variable': 'geopotential', 'pressure_level': str(lev),
                   'year': [str(y) for y in range(1991, 2021)], 'month': [f'{m:02d}' for m in range(1, 13)], 'time': '00:00', 'area': [90, -180, 20, 180], 'grid': [GRID, GRID], 'data_format': 'netcdf'}, f)
        ds = xr.open_dataset(f); z = ds['z'].squeeze().values / 9.80665; t = ds[[k for k in ds.coords if 'time' in k][0]].values
        la = ds['latitude'].values; lo = ds['longitude'].values; lo = np.where(lo > 180, lo - 360, lo); o = np.argsort(lo); z = z[..., o]
        if la[0] < la[-1]: z = z[..., ::-1, :]
        months = np.array([int(str(x)[5:7]) for x in t]); res[lev] = (z, months)
    out = {}
    for k, (iid, fa_, en, lev, dom, sg) in SPEC.items():
        z, months = res[lev]; clim = np.stack([z[months == m].mean(0) for m in range(1, 13)]); anom = z - clim[months - 1]; mask = domain_mask(dom)
        pat = build_eof(anom, mask, sg); out[f'{k}_clim'] = clim; out[f'{k}_pat'] = pat; out[f'{k}_sig'] = monthly_sigma(anom, pat, mask, months)
    np.savez_compressed(path, **out); log('✓ اقلیم و EOF ذخیره شد:', path)

# ───────── ECMWF open-data ─────────
def fetch_ens(workdir):
    """خروجی: init (date), {lev: (ctrl[steps,lat,lon], mean_pf[steps,lat,lon], npf)} — شبکهٔ ۲٫۵°.
    اجرای ۰۰Z/۱۲Z تا ۳۶۰ ساعت است (۰۶Z/۱۸Z فقط تا ۱۴۴)؛ پس ابتدا time=0 سپس time=12 را امتحان می‌کنیم و اگر کنترل (cf) نبود، فقط میانگین اعضا."""
    from ecmwf.opendata import Client
    import xarray as xr
    cl = Client(source='ecmwf'); res = {}; init = None; used = None; last_err = None
    for tm in (0, 12):
        for typ in ('cf', 'pf'):
            f = os.path.join(workdir, f'ens_{typ}_{tm}.grib2')
            try:
                cl.retrieve(type=typ, stream='enfo', time=tm, param='gh', levtype='pl', levelist=[500, 1000], step=STEPS, target=f)
            except Exception as e:
                last_err = e; log(f'  ؟ time={tm} type={typ}: {str(e)[:160]}'); continue
            for lev in (500, 1000):
                ds = xr.open_dataset(f, engine='cfgrib', backend_kwargs={'filter_by_keys': {'typeOfLevel': 'isobaricInhPa', 'level': lev}, 'indexpath': ''})
                a = ds['gh'].values; init = dt.date.fromisoformat(str(ds['time'].values)[:10]) if init is None else init
                npf = 0
                if typ == 'pf': npf = a.shape[0] if a.ndim == 4 else 1; a = a.mean(0) if a.ndim == 4 else a
                g = coarsen(a, ds['latitude'].values, ds['longitude'].values); res.setdefault(lev, {})[typ] = (g, npf)
        if res and all('pf' in v for v in res.values()): used = tm; break
        res = {}; init = None
    if not res: raise RuntimeError(f'ECMWF open-data در دسترس نبود: {last_err}')
    log(f'  ECMWF ENS: اجرای {used:02d}Z، تاریخ {init}')
    out = {}
    for lev, v in res.items():
        pf, npf = v['pf']; cf = v['cf'][0] if 'cf' in v else pf               # بدون کنترل: میانگین اعضا جایگزین
        out[lev] = (cf, pf, npf)
    return init, out

def hist_get(host, iid, requests):
    try:
        r = requests.get(f'{host.rstrip("/")}/data/idx/{iid}.json', timeout=30)
        if r.ok: j = r.json(); return [dt.date.fromisoformat(x) for x in j['obs']['t']], list(j['obs']['v'])
    except Exception: pass
    return [], []

def make_G(init, ctrl, mean, hist_t, hist_v):
    steps = np.array(STEPS) // 24; d = [init + dt.timedelta(days=int(s)) for s in steps]
    ot = [x for x in hist_t if x < init] + [init]; ov = [v for x, v in zip(hist_t, hist_v) if x < init] + [float(ctrl[0])]      # گام ۰ = تحلیل
    ot, ov = ot[-120:], ov[-120:]
    F = np.vstack([ctrl, mean])
    return dict(obs_t=ot, obs_v=np.array(ov), obs_end=ot[-1], init=init, lead=steps, fc=F, members=2, leads=(0, int(steps[-1])), age=(dt.datetime.now(dt.timezone.utc).date() - init).days)

def ser_ec(G):
    ot, ov = G['obs_t'], G['obs_v']; F = G['fc']
    return {'kind': 'plume', 'obs': {'t': [d.isoformat() for d in ot], 'v': list(ov)}, 'fc': {'init': G['init'].isoformat(), 'lead': [int(x) for x in G['lead']], 'mem': [list(F[0])], 'mean': list(F[1]), 'memLabel': 'control'}}

def mock_inputs():
    rng = np.random.default_rng(7); init = dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=1)
    clim = {k: np.stack([5500 - 3 * np.arange(len(LATS))[:, None] * np.ones((1, len(LONS))) + 20 * np.sin(m / 2) for m in range(12)]) for k in SPEC}
    return init, rng

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--host'); ap.add_argument('--key'); ap.add_argument('--out'); ap.add_argument('--mock', action='store_true'); ap.add_argument('--build-clim', action='store_true', dest='bc'); ap.add_argument('--only')
    a = ap.parse_args(); import requests
    if a.bc: build_clim(); return
    now = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d'); ok = fail = 0
    if a.mock:
        init, rng = mock_inputs(); data = None
    else:
        if not os.path.isfile(CLIM): sys.exit('✗ ecmwf_idx_clim.npz نیست؛ ابتدا: python ecmwf_indices.py --build-clim (CDSAPI_KEY لازم)')
        import tempfile; C = np.load(CLIM); init, data = fetch_ens(tempfile.mkdtemp())
    for k, (iid, fa_, en, lev, dom, sg) in SPEC.items():
        if a.only and k not in a.only.split(','): continue
        try:
            d = [init + dt.timedelta(days=s) for s in range(0, 16)]
            if a.mock:
                lead = np.arange(0, 16); base = rng.normal(0, 1); ctrl = base * .93 ** lead + rng.normal(0, .25, 16).cumsum() * .15; mean = ctrl * np.exp(-lead / 9.)
            else:
                cf, pf, npf = data[lev]; mask = domain_mask(dom); clim = C[f'{k}_clim']; pat = C[f'{k}_pat']; sig = C[f'{k}_sig']
                ctrl = index_series(cf, d, clim, pat, mask, sig); mean = index_series(pf, d, clim, pat, mask, sig)
            ht, hv = ([], []) if (a.mock or not a.host) else hist_get(a.host, iid, requests)
            G = make_G(init, ctrl, mean, ht, hv)
            if G['age'] > 5: raise ValueError(f'ران {G["age"]} روز کهنه است')
        except Exception as e: log(f'✗ {iid}: {e}'); fail += 1; continue
        spec = (iid, fa_, en, '', 'idx', f'Z{lev}')
        meta = dict(fa=fa_, en=f'{en} · ECMWF ENS (MetStat-computed)', grp=GRP, src='ECMWF open data (ENS) + ERA5 climatology · computed by MetStat', last=f'{init:%Y-%m-%d}', upd=now, unit='', kind='plume', mdl='ecmwf',
                    note=f'ECMWF ENS Z{lev}: کنترل + میانگین اعضا؛ «محاسبهٔ MetStat» — شاخص رسمی NOAA/ECMWF نیست')
        meta.update(IX.gefs_summary(G)); ser = IX.ser_bytes(ser_ec(G)); first = True
        if a.out: os.makedirs(a.out, exist_ok=True); open(os.path.join(a.out, f'{iid}.json'), 'wb').write(ser)
        for per, days in IX.GEFS_PERIODS.items():
            png = IX.render_gefs(k, G, days, meta, label='ECMWF ENS', srcname='ECMWF open data + ERA5 clim. · computed by MetStat', members_txt='control + ensemble mean', spec=spec)
            if a.out: open(os.path.join(a.out, f'{iid}_{per}.png'), 'wb').write(png)
            if a.host: IX.post(a, iid, per, png, dict(meta, perfa=f'{IX.fa(days)} روز اخیر + پیش‌بینی'), requests, ser if first else None); first = False
        log(f'✓ {iid} (ران {init}، کنترل+میانگین)'); ok += 1
    if a.host: requests.post(f'{a.host.rstrip("/")}/nwp_upload.php?a=idxend&key={requests.utils.quote(a.key)}', timeout=60)
    log(f'پایان: {ok} موفق، {fail} ناموفق'); sys.exit(0 if ok else 1)

if __name__ == '__main__': main()

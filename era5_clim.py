# -*- coding: utf-8 -*-
"""MetStat r192 — اقلیم ERA5 برای نقشه‌های انومالی (Z500/Z700/Z850 و MSLP).
منبع: WeatherBench2 «era5-hourly-climatology» (ERA5، دورهٔ ۱۹۹۰–۲۰۱۹، میانگین‌گیری هموارشدهٔ هر روز سال)، بایگانی عمومی گوگل‌کلود.
خروجی: data/static/era5_clim_1deg.npz — میانگین روزانه (۳۶۶ روز) روی شبکهٔ ۱° (لنگرهای ۰٫۲۵° هر ۴ نقطه) برای lon −15…95، lat 5…65.
اثر تغییرات روزانهٔ جزرومد جوی (≤۱–۲ m در Z500، ≤۱ hPa در MSLP) نادیده گرفته می‌شود؛ در برابر انومالی‌های ده‌ها متر/چند hPa ناچیز است."""
import sys, numpy as np, xarray as xr
URL = 'gs://weatherbench2/datasets/era5-hourly-climatology/1990-2019_6h_1440x721.zarr'
ds = xr.open_zarr(URL, storage_options={'token': 'anon'}, chunks=None)
print(dict(ds.sizes), list(ds.data_vars)[:20], flush=True)
lat = ds['latitude'].values; lon = ds['longitude'].values
def sel(da):
    da = da.sortby('latitude')
    lons = np.arange(-15, 95.1, 1.0); lats = np.arange(5, 65.1, 1.0)
    da = da.assign_coords(longitude=((da.longitude + 180) % 360) - 180) if da.longitude.max() > 180 else da
    da = da.sortby('longitude')
    return da.sel(latitude=lats, longitude=lons, method='nearest')
out = {}
G = ds['geopotential']
for L in (500, 700, 850):
    a = sel(G.sel(level=L)).mean('hour').compute().values / 9.80665          # m
    out[f'z{L}'] = a.astype(np.float16); print('z', L, a.shape, float(np.nanmin(a)), float(np.nanmax(a)), flush=True)
m = sel(ds['mean_sea_level_pressure']).mean('hour').compute().values / 100.0       # hPa
out['msl'] = m.astype(np.float16); print('msl', m.shape, float(np.nanmin(m)), float(np.nanmax(m)), flush=True)
# Temperature must come from the same ERA5 climatology, not from a regional substitute.
temperature_key = next((k for k in ('2m_temperature', 'temperature_2m', 't2m') if k in ds.data_vars), None)
if temperature_key is None:
    raise KeyError('ERA5 climatology lacks 2m temperature; available variables: ' + ', '.join(ds.data_vars))
t2m = sel(ds[temperature_key]).mean('hour').compute().values
if not (np.isfinite(t2m).all() and 170 < float(np.nanmin(t2m)) < 330 and 220 < float(np.nanmax(t2m)) < 350):
    raise ValueError('ERA5 2m temperature must be finite and expressed in Kelvin')
out['t2m'] = t2m.astype(np.float16)
print('t2m K', t2m.shape, float(np.nanmin(t2m)), float(np.nanmax(t2m)), flush=True)
out['lat'] = np.arange(5, 65.1, 1.0, dtype=np.float32); out['lon'] = np.arange(-15, 95.1, 1.0, dtype=np.float32)
for key in ('z500', 'z700', 'z850', 'msl', 't2m'):
    if out[key].shape[-2:] != (61, 111):
        raise ValueError(f'Unexpected ERA5 grid for {key}: {out[key].shape}')
np.savez_compressed('data/static/era5_clim_1deg.npz', **out)
import os; print('saved', os.path.getsize('data/static/era5_clim_1deg.npz') // 1024, 'KB')

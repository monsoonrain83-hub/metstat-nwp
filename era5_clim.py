# -*- coding: utf-8 -*-
"""Build a regional ERA5 daily climatology from WeatherBench2 (1990–2019).

This is a *reference climatology*, not forecast data. Output is not published
until consumers explicitly validate its coverage and units.
"""
import os
import numpy as np
import xarray as xr

URL = "gs://weatherbench2/datasets/era5-hourly-climatology/1990-2019_6h_1440x721.zarr"
OUT = "data/static/era5_clim_1deg.npz"
LONS = np.arange(-15, 95.1, 1.0, dtype=np.float32)
LATS = np.arange(5, 65.1, 1.0, dtype=np.float32)


def select_region(da):
    """Select geographic coordinates without accidentally extrapolating."""
    if float(da.longitude.max()) > 180:
        da = da.assign_coords(longitude=((da.longitude + 180) % 360) - 180)
    return da.sortby("latitude").sortby("longitude").sel(
        latitude=LATS, longitude=LONS, method="nearest"
    )


def daily_field(da, divisor=1.0):
    """Keep 366 day-of-year climatology slices; average the 6-hour slots."""
    regional = select_region(da)
    if "hour" not in regional.dims:
        raise ValueError("ERA5 climatology lacks 6-hour time-of-day dimension")
    daily = (regional.mean("hour") / divisor).compute()
    values = np.asarray(daily.values, dtype=np.float32)
    if values.shape != (366, len(LATS), len(LONS)):
        raise ValueError(f"Unexpected ERA5 climatology shape: {values.shape}")
    if not np.isfinite(values).all():
        raise ValueError("ERA5 climatology has missing/nonfinite regional values")
    return values


def build(ds):
    out = {"lat": LATS, "lon": LONS}
    geopotential = ds["geopotential"]
    for level in (500, 700, 850):
        values = daily_field(geopotential.sel(level=level), 9.80665)
        if not (0 < values.min() and values.max() < 20000):
            raise ValueError(f"Unphysical Z{level} climatology")
        out[f"z{level}"] = values.astype(np.float16)
    pressure = daily_field(ds["mean_sea_level_pressure"], 100.0)
    if not (800 < pressure.min() and pressure.max() < 1150):
        raise ValueError("MSLP climatology unit/physical range mismatch")
    out["msl"] = pressure.astype(np.float16)
    # The surface 2m temperature is required for ME/EU temperature anomalies.
    # Store in Celsius to match the forecast pipeline; do not infer a
    # temperature climatology from Iranian station normals.
    t2m = daily_field(ds["2m_temperature"])
    if not (170 < t2m.min() and t2m.max() < 350):
        raise ValueError("ERA5 2m temperature is not in expected Kelvin range")
    out["t2m"] = (t2m - 273.15).astype(np.float16)
    return out


def main():
    ds = xr.open_zarr(URL, storage_options={"token": "anon"}, chunks=None)
    print(dict(ds.sizes), list(ds.data_vars), flush=True)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    result = build(ds)
    np.savez_compressed(OUT, **result)
    print("saved", OUT, os.path.getsize(OUT), "bytes", sorted(result), flush=True)


if __name__ == "__main__":
    main()

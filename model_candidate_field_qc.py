#!/usr/bin/env python3
"""Read actual cropped native OM fields for newly discovered NWP models.

This is deliberately NOT a production ingestion pipeline: it samples a
single same-cycle OM file, records units as tentative, never claims globe
registration from array shape, never generates maps or uploads to cPanel.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory

from model_source_inventory_probe import SOURCES, inspect_manifest, s3_fetcher
from model_grid_shape_probe import om_uri, to_utc

ALLOWED = ("aigfs", "grapes", "jma")
FIELDS = ("temperature_2m", "geopotential_height_500hPa", "precipitation")
MAX_POINTS = 256


def evaluate_sample(variable: str, values) -> dict:
    """QC the raw sample; it does not validate full domain or source semantics."""
    import numpy as np

    if variable not in FIELDS:
        raise ValueError("unexpected field")
    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 2 or array.size < 16 or array.size > MAX_POINTS:
        raise ValueError("invalid sample shape")
    finite = np.isfinite(array)
    frac = float(finite.mean())
    if frac < .875:
        return {"field": variable, "passed": False, "reason": "missing-sample-data",
                "finite_fraction": round(frac, 4)}
    finite_values = array[finite]
    low, median, high = [float(fn(finite_values)) for fn in (np.min, np.median, np.max)]
    inferred = "unknown"
    if variable == "temperature_2m":
        if 175 <= median <= 345 and low > 100 and high < 380:
            inferred = "K"
        elif -100 < median < 65 and low > -125 and high < 95:
            inferred = "°C"
    elif variable == "geopotential_height_500hPa":
        if 400 <= median <= 700 and 200 <= low <= high < 1000:
            inferred = "dam"
        elif 4000 <= median <= 7000 and 2000 <= low <= high < 10000:
            inferred = "m"
        elif 40000 <= median <= 70000 and 15000 <= low <= high < 100000:
            inferred = "m²/s²"
    elif variable == "precipitation":
        if low >= -0.0001 and median >= 0 and high < 20000:
            inferred = "raw accumulation (interval/unit unverified)"
    return {"field": variable, "passed": inferred != "unknown",
            "finite_fraction": round(frac, 4),
            "min_raw": round(low, 5), "median_raw": round(median, 5),
            "max_raw": round(high, 5), "tentative_units": inferred,
            "full_grid_qc": False}


def sample_om(uri: str, variables: list[str]) -> dict:
    import fsspec
    import numpy as np
    from omfiles import OmFileReader

    if not uri.startswith("s3://openmeteo/data_spatial/") or not uri.endswith(".om"):
        raise ValueError("disallowed source URL")
    found = {}
    with TemporaryDirectory(prefix="metstat-qc-") as cache:
        f = fsspec.open(f"blockcache::{uri}", mode="rb",
                        s3={"anon": True, "default_block_size": 65536},
                        blockcache={"cache_storage": cache})
        with OmFileReader(f) as root:
            for variable in variables:
                if variable not in FIELDS:
                    raise ValueError("unauthorized field")
                try:
                    c = root.get_child_by_name(variable)
                except (KeyError, ValueError):
                    continue
                if c is None or not c.is_array or len(c.shape) != 2:
                    continue
                ny, nx = tuple(c.shape)
                if ny < 16 or nx < 16:
                    continue
                j0, i0 = ny//2-8, nx//2-8
                raw = np.asarray(c[j0:j0+16, i0:i0+16], dtype=np.float32)
                found[variable] = {"shape": [ny, nx], "sample": raw}
    return found


def probe_model(name: str, fetch, sampler) -> dict:
    if name not in ALLOWED:
        raise ValueError("model has not passed source metadata discovery")
    domain = SOURCES[name]["domains"][0]
    latest_path = f"openmeteo/data_spatial/{domain}/latest.json"
    try:
        latest = fetch(latest_path)
        meta = inspect_manifest(latest)
        times = latest.get("valid_times") or []
        if not meta["reference_time"] or not times:
            raise ValueError("run and valid times are required")
        # Do not probe the analysis hour for precipitation: accumulation
        # cannot be established at step 0. Prefer an actual forecast valid
        # instant within +6..24h from the *same* initialization.
        run_dt = to_utc(meta["reference_time"])
        eligible = [t for t in times if
                    6 <= (to_utc(str(t)) - run_dt).total_seconds() / 3600 <= 24]
        if not eligible:
            raise ValueError("no forecast valid instant between +6h and +24h")
        # Manifests may list valid times out of order; choose the earliest valid forecast instant.
        probe_valid = str(min(eligible, key=lambda t: to_utc(str(t))))
        uri = om_uri(domain, meta["reference_time"], probe_valid)
        variables = [f for f in FIELDS if f in meta["all_variable_names"]]
        if not variables:
            raise ValueError("no required weather variables in source")
        fields = sampler(uri, variables)
        qc = []
        common_shape = None
        for v in variables:
            if v not in fields:
                qc.append({"field": v, "passed": False, "reason": "not-found-in-om-file"})
                continue
            shp = fields[v].get("shape")
            if not isinstance(shp, (tuple, list)) or len(shp) != 2:
                raise ValueError("invalid shape metadata")
            if common_shape is None:
                common_shape = list(shp)
            if list(shp) != common_shape:
                qc.append({"field": v, "passed": False, "reason": "per-field-shape-mismatch"})
                continue
            qc.append(evaluate_sample(v, fields[v]["sample"]))
        return {"model": name, "domain": domain, "run_utc": meta["reference_time"],
                "valid_utc": probe_valid, "source_om": uri,
                "grid_shape": common_shape,
                "fields": qc, "sample_qc_passed": bool(qc) and all(x["passed"] for x in qc),
                "coverage_qc_passed": False, "projection_verified": False,
                "precipitation_accumulation_verified": False,
                "production_ready": False}
    except Exception as exc:
        return {"model": name, "domain": domain, "sample_qc_passed": False,
                "production_ready": False, "reason": str(exc)[:220]}


def run(fields=None, fetch=None, sampler=None):
    if fields is None:
        fields = list(ALLOWED)
    if any(name not in ALLOWED for name in fields):
        raise ValueError("unsupported model selection")
    if fetch is None:
        fetch = s3_fetcher()
    if sampler is None:
        sampler = sample_om
    return {"schema": 1, "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "read_only": True, "samples": [probe_model(m, fetch, sampler) for m in fields]}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--models", nargs="+", default=list(ALLOWED), choices=list(ALLOWED))
    p.add_argument("--json-out", type=Path, required=True)
    args = p.parse_args()
    report = run(args.models)
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps([{"model": x["model"], "sample_qc_passed": x["sample_qc_passed"],
                       "production_ready": x["production_ready"]} for x in report["samples"]]))


if __name__ == "__main__":
    main()

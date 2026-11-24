#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only discovery of real Open-Meteo S3 model run manifests.

Does not download meteorological arrays, change production MODELS/GRIDS, or
publish to the site. Unknown grid/field/time metadata is reported as unknown,
not guessed. KMA GDPS is intentionally never marked production-ready.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

# Independent sources must never be treated as two resolution aliases of the
# same deterministic model, or counted as extra ECMWF/GFS multi-model votes.
SOURCES = {
    "aifs": {"domains": ("ecmwf_aifs025",), "family": "ecmwf-ai", "provider": "ECMWF"},
    "aigfs": {"domains": ("ncep_aigfs025",), "family": "noaa-ai", "provider": "NOAA"},
    "graphcast": {"domains": ("gfs_graphcast025", "ncep_gfs_graphcast025"),
                  "family": "graphcast", "provider": "Google/NOAA"},
    "grapes": {"domains": ("cma_grapes_global",), "family": "cma", "provider": "CMA"},
    "jma": {"domains": ("jma_gsm",), "family": "jma", "provider": "JMA"},
    "kma": {"domains": ("kma_gdps",), "family": "kma", "provider": "KMA",
            "retired": True},  # Open-Meteo: discontinued 2026-03-31
    "weathernext": {"domains": ("google_weathernext2_ensemble",),
                    "family": "google-ensemble", "provider": "Google", "ensemble": True},
}
BUCKET = "openmeteo"
PREFIX = "data_spatial"
LIMIT = 512_000
PRESSURE_LEVELS = (1000, 925, 850, 700, 600, 500, 400, 300, 250, 200, 150, 100)
BASE_FIELDS = (
    "temperature_2m", "relative_humidity_2m", "pressure_msl",
    "surface_pressure", "precipitation", "wind_u_component_10m",
    "wind_v_component_10m", "cape", "snowfall_water_equivalent",
)
UPPER_FIELDS = ("geopotential_height", "temperature", "relative_humidity",
                "wind_u_component", "wind_v_component", "vertical_velocity")


def inspect_manifest(data: Any) -> dict:
    if not isinstance(data, dict):
        raise ValueError("latest.json is not an object")
    variable_data = data.get("variables")
    if isinstance(variable_data, dict):
        variables = list(variable_data)
    elif isinstance(variable_data, list) and all(isinstance(v, str) for v in variable_data):
        variables = variable_data
    else:
        raise ValueError("latest.json has no usable variables array/object")
    if len(variables) != len(set(variables)):
        raise ValueError("duplicate variable names in manifest")
    times = data.get("valid_times")
    if times is not None and not isinstance(times, list):
        raise ValueError("valid_times must be an array when provided")
    if isinstance(times, list) and len({str(x) for x in times}) != len(times):
        raise ValueError("duplicate forecast valid times")
    available = set(variables)
    levels = {field: [level for level in PRESSURE_LEVELS
                      if f"{field}_{level}hPa" in available]
              for field in UPPER_FIELDS}
    grid = {}
    # Report only actual metadata keys; never silently assign a synthetic grid.
    for key in ("nx", "ny", "latitude_min", "longitude_min", "dx", "dy",
                "grid", "shape", "spatial_shape", "n_latitudes",
                "n_longitudes", "resolution"):
        if key in data and isinstance(data[key], (dict, list, int, float, str)):
            grid[key] = data[key]
    return {
        "reference_time": data.get("reference_time"),
        "forecast_valid_time_count": len(times) if isinstance(times, list) else None,
        "first_valid_time": times[0] if times else None,
        "last_valid_time": times[-1] if times else None,
        "variable_count": len(available),
        "surface_fields_available": [field for field in BASE_FIELDS if field in available],
        "pressure_levels_available": levels,
        "grid_metadata_from_latest_json": grid or None,
        "grid_verified_from_latest_json": bool(grid),
        "all_variable_names": sorted(available),
    }


def inspect_source(fetch_json, name: str, spec: dict) -> dict:
    if name not in SOURCES:
        raise ValueError("unknown, unauthorised source")
    records = []
    for domain in spec["domains"]:
        path = f"{BUCKET}/{PREFIX}/{domain}/latest.json"
        try:
            raw = fetch_json(path)
            meta = inspect_manifest(raw)
            records.append({"domain": domain, "ok": True, **meta})
        except (OSError, ValueError, KeyError, RuntimeError, TypeError, json.JSONDecodeError) as exc:
            records.append({"domain": domain, "ok": False, "error": str(exc)[:160]})
    valid = [item for item in records if item["ok"]]
    return {
        "model": name,
        "family": spec["family"],
        "owner": spec["provider"],
        "retired_upstream": bool(spec.get("retired")),
        "ensemble": bool(spec.get("ensemble")),
        "candidates": records,
        "source_readable": bool(valid),
        # This probe alone can NEVER prove a working NWP pipeline.
        "production_ready": False,
        "requires_field_decode_grid_qc": True,
    }


def run_probe(fetch_json, names: list[str] | None = None) -> dict:
    targets = names or list(SOURCES)
    if not targets or any(n not in SOURCES for n in targets):
        raise ValueError("only approved model names can be probed")
    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "read_only": True,
        "results": [inspect_source(fetch_json, name, SOURCES[name]) for name in targets],
    }


def s3_fetcher():
    import fsspec
    fs = fsspec.filesystem("s3", anon=True, client_kwargs={"region_name": "us-west-2"})
    def fetch(path: str):
        # Allowed exact bucket/key shape, no arbitrary network URL or wildcards.
        if not path.startswith(f"{BUCKET}/{PREFIX}/") or not path.endswith("/latest.json"):
            raise ValueError("disallowed object path")
        size = fs.info(path).get("size")
        if size is None or not 0 < int(size) <= LIMIT:
            raise ValueError("model manifest missing, empty or too large")
        raw = fs.cat_file(path)
        if len(raw) > LIMIT:
            raise ValueError("model manifest too large")
        return json.loads(raw.decode("utf-8"))
    return fetch


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Probe seven model sources without downloads")
    p.add_argument("--models", nargs="+", choices=tuple(SOURCES))
    p.add_argument("--json-out", type=Path)
    args = p.parse_args(argv)
    report = run_probe(s3_fetcher(), args.models)
    payload = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    # A missing/retired domain is a discovery result, not cause to mutate prod.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

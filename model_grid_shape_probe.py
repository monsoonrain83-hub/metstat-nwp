#!/usr/bin/env python3
"""Read only the OM-File header for a discovered model/run/valid instant.

A shape is NOT geographic registration: it does not establish projection,
longitude ordering or global coverage. Production GRIDS must not be modified.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from model_source_inventory_probe import SOURCES, s3_fetcher, inspect_manifest

MAX_SHAPE = 50_000
PREFERRED_FIELDS = ("temperature_2m", "pressure_msl", "geopotential_height_500hPa",
                    "precipitation")


def to_utc(value: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be text")
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("naive timestamp")
    return dt.astimezone(timezone.utc)


def om_uri(domain: str, reference_time: str, valid_time: str) -> str:
    if domain not in {d for v in SOURCES.values() for d in v["domains"]}:
        raise ValueError("source domain is not allowed")
    run, valid = to_utc(reference_time), to_utc(valid_time)
    if valid < run or (valid - run).days > 17:
        raise ValueError("unreasonable forecast valid time")
    return (f"s3://openmeteo/data_spatial/{domain}/"
            f"{run:%Y/%m/%d/%H%M}Z/{valid:%Y-%m-%dT%H%M}.om")


def inspect_one(domain: str, source_json: dict, opener) -> dict:
    meta = inspect_manifest(source_json)
    times = source_json.get("valid_times") or []
    if not times or not meta["reference_time"]:
        return {"domain": domain, "shape_verified": False, "reason": "no-run-or-valid-times"}
    # Some products have frames whose files are released later. Try the most
    # recent listed valid timestamp first, without pretending absence is proof.
    uri = om_uri(domain, meta["reference_time"], str(times[0]))
    fields = [f for f in PREFERRED_FIELDS if f in set(meta["all_variable_names"])]
    if not fields:
        return {"domain": domain, "shape_verified": False, "reason": "no-supported-variable"}
    try:
        found = opener(uri, fields)
        shape = found.get("shape")
        if (not isinstance(shape, (tuple, list)) or len(shape) != 2 or
                any(type(n) is not int or n <= 0 or n > MAX_SHAPE for n in shape)):
            raise ValueError("OM shape is not a plausible 2-D grid")
        return {
            "domain": domain, "shape_verified": True,
            "run_utc": meta["reference_time"], "valid_utc": str(times[0]),
            "om_source": uri, "variable": found["variable"],
            "rows_ny": shape[0], "columns_nx": shape[1],
            "coordinate_extent_verified": False,
            "ready_for_publishing": False,
        }
    except Exception as exc:
        return {"domain": domain, "shape_verified": False,
                "om_source": uri, "reason": str(exc)[:190]}


def open_om_header(uri: str, fields: list[str]) -> dict:
    import fsspec
    from omfiles import OmFileReader
    with TemporaryDirectory(prefix="metstat-om-meta-") as cache:
        backend = fsspec.open(
            f"blockcache::{uri}", mode="rb",
            s3={"anon": True, "default_block_size": 65536},
            blockcache={"cache_storage": cache},
        )
        with OmFileReader(backend) as root:
            for field in fields:
                try:
                    reader = root.get_child_by_name(field)
                except (KeyError, ValueError):
                    continue
                if reader is not None and reader.is_array:
                    return {"variable": field, "shape": tuple(reader.shape)}
    raise ValueError("no expected field found in OM file")


def run_model_shapes(model_names: list[str], fetch_json, opener) -> dict:
    out = []
    for name in model_names:
        if name not in SOURCES:
            raise ValueError("model not approved")
        spec = SOURCES[name]
        # Retired KMA must never be represented as a current valid forecast.
        if spec.get("retired") or spec.get("ensemble"):
            out.append({"model": name, "shape_verified": False,
                        "reason": "retired-or-ensemble-not-deterministic"})
            continue
        for domain in spec["domains"]:
            try:
                meta = fetch_json(f"openmeteo/data_spatial/{domain}/latest.json")
                result = inspect_one(domain, meta, opener)
            except Exception as exc:
                result = {"domain": domain, "shape_verified": False, "reason": str(exc)[:160]}
            out.append({"model": name, **result})
            if result["shape_verified"]:
                break
    return {"schema": 1, "read_only": True, "grid_shapes": out}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", default=["aigfs", "grapes", "jma"],
                    choices=list(SOURCES))
    ap.add_argument("--json-out", type=Path, required=True)
    args = ap.parse_args()
    report = run_model_shapes(args.models, s3_fetcher(), open_om_header)
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n")
    for row in report["grid_shapes"]:
        print(row)


if __name__ == "__main__":
    main()

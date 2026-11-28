"""Verified multi-lead run store, isolated from the legacy world-data tree.

Run on a trusted local POSIX filesystem with a dedicated output root.
The operator supplies the exact required lead policy and a per-model byte budget.
Only complete baseline runs enter the catalog; keep two, never prune unknown files.
"""
import argparse
import fcntl
import json
import os
import re
import shutil
import tempfile
from datetime import timezone, timedelta
from pathlib import Path

from PIL import Image
from pack_global_products import (
    EXPECTED_UNITS, MODEL_LICENSE, parse_utc, verify_manifest_field,
)

FIELDS = set(EXPECTED_UNITS)
RUN_ID = re.compile(r"[0-9]{12}Z")


def read_json(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError("not a regular manifest: " + str(path))
    if path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError("manifest too large")
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def size_tree(path):
    total = 0
    for item in path.rglob("*"):
        if item.is_symlink():
            raise ValueError("symlink in managed store")
        if item.is_file():
            total += item.stat().st_size
        elif not item.is_dir():
            raise ValueError("unexpected special file in store")
    return total


def validate_plan(leads):
    leads = list(leads)
    if not leads or len(set(leads)) != len(leads) or any(
        type(h) is not int or not 0 <= h <= 384 for h in leads
    ):
        raise ValueError("invalid required leads")
    return sorted(leads)


def verify_run(src, model, required_leads, staging, budget):
    series = read_json(src / "series.json")
    if (series.get("schema") != 1 or series.get("model") != model
            or series.get("complete") is not True
            or validate_plan(series.get("requested_leads", [])) != required_leads
            or set(series.get("leads", {})) != {str(h) for h in required_leads}):
        raise ValueError("incomplete or unexpected lead inventory")
    run = parse_utc(series["init_utc"])
    stamp = run.strftime("%Y%m%d%H%MZ")
    output = {"schema": 1, "model": model, "run_id": stamp,
              "init_utc": series["init_utc"], "required_leads": required_leads,
              "source_license": MODEL_LICENSE[model], "leads": {}}
    used = 0
    for h in required_leads:
        name = f"f{h:03d}"
        entry = series["leads"][str(h)]
        if (entry.get("status") != "available" or entry.get("missing_fields") != []
                or set(entry.get("available_fields", [])) != FIELDS
                or entry.get("manifest") != name + "/manifest.json"):
            raise ValueError("missing field or unexpected manifest path")
        folder = src / name
        if folder.is_symlink():
            raise ValueError("symlink lead directory")
        man = read_json(folder / "manifest.json")
        if (man.get("schema") != 2 or man.get("model") != model
                or man.get("full_globe") is not True or man.get("mock") is not False
                or man.get("bbox_wgs84") != [-180, -90, 180, 90]
                or man.get("projection") != "EPSG:4326 equirectangular"
                or man.get("longitude_orientation") != "west_to_east"
                or man.get("latitude_orientation") != "north_to_south"
                or man.get("init_utc") != series["init_utc"]
                or parse_utc(man["valid_utc"]) != run + timedelta(hours=h)
                or set(man.get("fields", {})) != FIELDS):
            raise ValueError("invalid global frame provenance")
        target = staging / name
        target.mkdir()
        fields = {}
        for param in sorted(FIELDS):
            field = man["fields"][param]
            if field.get("variable") != {"t2m": "temperature_2m", "mslp": "pressure_msl",
                                        "z500": "geopotential_height_500hPa"}[param]:
                raise ValueError("wrong physical variable")
            raster = folder / f"{model}_{param}_{(run + timedelta(hours=h)):%Y%m%d%H}.webp"
            if raster.is_symlink() or not raster.is_file():
                raise ValueError("invalid raster file")
            if raster.stat().st_size > budget - used:
                raise RuntimeError("byte budget exceeded before publication")
            data, checksum = verify_manifest_field(model, param, field, man, folder)
            if len(data) > budget - used:
                raise RuntimeError("byte budget exceeded before publication")
            # Decode the actual checked bytes, not just RIFF header and metadata.
            import io
            with Image.open(io.BytesIO(data)) as image:
                if (image.format != "WEBP" or image.size != (field["width"], field["height"])
                        or getattr(image, "n_frames", 1) != 1):
                    raise ValueError("raster dimensions or format mismatch")
                image.load()
            with (target / (param + ".webp")).open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            used += len(data)
            fields[param] = {**field, "file": f"{name}/{param}.webp", "sha256": checksum}
        output["leads"][str(h)] = {"valid_utc": man["valid_utc"], "fields": fields}
        sync_dir(target)
    write_json(staging / "run.json", output)
    sync_dir(staging)
    if size_tree(staging) > budget:
        raise RuntimeError("byte budget exceeded including manifest")
    return stamp, output


def publish(src, root, model, required_leads, max_bytes, reserve_bytes=0):
    if model not in MODEL_LICENSE:
        raise ValueError("unknown model")
    required_leads = validate_plan(required_leads)
    if type(max_bytes) is not int or max_bytes <= 0 or type(reserve_bytes) is not int or reserve_bytes < 0:
        raise ValueError("invalid storage limits")
    src, root = Path(src), Path(root)
    if src.is_symlink() or root.is_symlink():
        raise ValueError("symlink root")
    if src.resolve().is_relative_to(root.resolve()) or root.resolve().is_relative_to(src.resolve()):
        raise ValueError("source and store must be disjoint")
    root.mkdir(parents=True, exist_ok=True)
    store = root / model
    if store.is_symlink():
        raise ValueError("symlink model store")
    store.mkdir(exist_ok=True)
    fd = os.open(store / ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "rb") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        pointer = store / "catalog.json"
        old = []
        if pointer.exists() or pointer.is_symlink():
            state = read_json(pointer)
            if state.get("schema") != 1 or state.get("model") != model:
                raise ValueError("unknown catalog")
            old = state["runs"]
            if (not isinstance(old, list) or not 1 <= len(old) <= 2
                    or any(not isinstance(x, str) or not RUN_ID.fullmatch(x) for x in old)
                    or old != sorted(set(old), reverse=True)):
                raise ValueError("invalid retention catalog")
            if state.get("latest") != old[0]:
                raise ValueError("invalid latest pointer")
            for item in old:
                if (store / item).is_symlink():
                    raise ValueError("symlink retained run")
                previous = read_json(store / item / "run.json")
                if previous.get("model") != model or previous.get("run_id") != item:
                    raise ValueError("unknown retained run")
                if previous.get("required_leads") != required_leads:
                    raise ValueError("lead policy changed; use a separate store")
        budget = min(max_bytes - size_tree(store),
                     shutil.disk_usage(store).free - reserve_bytes)
        if budget <= 0:
            raise RuntimeError("insufficient peak space; previous runs preserved")
        staging = Path(tempfile.mkdtemp(prefix=".incoming-", dir=store))
        installed = None
        temp_pointer = None
        committed = False
        try:
            stamp, _ = verify_run(src, model, required_leads, staging, budget)
            if old and stamp <= old[0]:
                raise ValueError("cycle not newer; previous runs preserved")
            final = store / stamp
            if final.exists() or final.is_symlink():
                raise ValueError("run directory already exists")
            kept = ([stamp] + old)[:2]
            new = {"schema": 1, "model": model, "latest": stamp, "runs": kept,
                   "required_leads": required_leads, "scope": "complete baseline series"}
            temp_pointer = staging / ".next-catalog"
            write_json(temp_pointer, new)
            if size_tree(staging) > budget:
                raise RuntimeError("byte budget exceeded including catalog")
            if shutil.disk_usage(store).free < reserve_bytes:
                raise RuntimeError("disk reserve reached before publication")
            os.rename(staging, final)
            installed = final
            temp_pointer = final / ".next-catalog"
            sync_dir(store)
            os.replace(temp_pointer, pointer)
            committed = True
            sync_dir(store)
        finally:
            if not committed:
                if installed is not None:
                    shutil.rmtree(installed)
                elif staging.exists():
                    shutil.rmtree(staging)
        # Delete ONLY runs named by the prior valid catalog, after durable switch.
        # Unknown directories and permanent archives outside this store are untouched.
        for item in old[1:]:
            shutil.rmtree(store / item)
        sync_dir(store)
        return new


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--src", type=Path, required=True)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--model", choices=sorted(MODEL_LICENSE), required=True)
    p.add_argument("--required-leads", type=int, nargs="+", required=True)
    p.add_argument("--max-bytes", type=int, required=True)
    p.add_argument("--reserve-bytes", type=int, default=0)
    a = p.parse_args()
    print(json.dumps(publish(a.src, a.root, a.model, a.required_leads,
                             a.max_bytes, a.reserve_bytes)))


if __name__ == "__main__":
    main()

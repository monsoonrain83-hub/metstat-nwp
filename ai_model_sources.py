#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 27: strict AI forecast source preflight. No host publishing.

AIFS Single -> ECMWF open data. AIGFS -> NOAA NOMADS GRIB2 indices.
These are separate AI models, not ECMWF/GFS resolution alternatives.
Only precipitation and Z500 are eligible for the first ME/Turkey rollout.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
import re

NOAA_ROOT = "https://nomads.ncep.noaa.gov/pub/data/nccf/com/aigfs/prod"
MAX_INDEX_BYTES = 512_000
ALLOWED_PARAMS = ("precipitation", "z500")


def validate(run: datetime, lead: int, model: str) -> datetime:
    if model not in ("aifs", "aigfs"):
        raise ValueError("unsupported AI model")
    if not isinstance(run, datetime) or run.tzinfo is None:
        raise ValueError("UTC-aware initialization required")
    run = run.astimezone(timezone.utc)
    if run.hour not in (0, 6, 12, 18) or run.minute or run.second or run.microsecond:
        raise ValueError("initialization must be an exact 00/06/12/18 UTC cycle")
    horizon = 360 if model == "aifs" else 384
    if type(lead) is not int or lead < 0 or lead > horizon or lead % 6:
        raise ValueError("invalid or unpublished forecast lead")
    return run


def aigfs_url(run: datetime, lead: int, parameter: str) -> str:
    run = validate(run, lead, "aigfs")
    if parameter not in ALLOWED_PARAMS:
        raise ValueError("unsupported AI product")
    group = "pres" if parameter == "z500" else "sfc"
    return (f"{NOAA_ROOT}/aigfs.{run:%Y%m%d}/{run:%H}/model/atmos/grib2/"
            f"aigfs.t{run:%H}z.{group}.f{lead:03d}.grib2.idx")


def has_grib_record(index: str, parameter: str) -> bool:
    if parameter not in ALLOWED_PARAMS:
        raise ValueError("unsupported AI product")
    for line in index.splitlines():
        parts = line.strip().split(":")
        if len(parts) < 6 or not parts[0].isdigit() or not parts[1].isdigit():
            continue
        name, level = parts[3].strip(), parts[4].strip().lower()
        if parameter == "z500" and name == "HGT" and re.fullmatch(r"500\s*(?:mb|hpa)", level):
            return True
        if parameter == "precipitation" and name == "APCP" and level == "surface":
            return True
    return False


def probe_aigfs(run: datetime, lead: int, parameter: str, timeout: int = 15) -> dict:
    run = validate(run, lead, "aigfs")
    url = aigfs_url(run, lead, parameter)
    req = Request(url, headers={"User-Agent": "MetStat-stage27-source-check/1.0"})
    with urlopen(req, timeout=timeout) as response:
        if not response.geturl().startswith("https://nomads.ncep.noaa.gov/"):
            raise ValueError("NOAA index redirected outside trusted host")
        raw = response.read(MAX_INDEX_BYTES + 1)
    if len(raw) > MAX_INDEX_BYTES:
        raise ValueError("index size limit exceeded")
    available = has_grib_record(raw.decode("ascii"), parameter)
    return dict(model="aigfs", init_utc=run.isoformat(), lead_hours=lead,
                parameter=parameter, source_index=url, verified_index=available)


def aifs_request(run: datetime, lead: int, parameter: str) -> dict:
    run = validate(run, lead, "aifs")
    if parameter not in ALLOWED_PARAMS:
        raise ValueError("unsupported AI product")
    fields = {"param": "tp"} if parameter == "precipitation" else {
        "param": "z", "levtype": "pl", "levelist": 500}
    return dict(stream="oper", type="fc", date=run.strftime("%Y%m%d"),
                time=run.hour, step=lead, **fields)


def stage_aifs_grib(run: datetime, lead: int, parameter: str, out_dir: Path) -> Path:
    """Explicit opt-in download only. Never replaces files or uploads anything."""
    req = aifs_request(run, lead, parameter)
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    final = out_dir / f"aifs_{run:%Y%m%d%H}_{parameter}_{lead:03d}.grib2"
    partial = final.with_suffix(".grib2.partial")
    if final.exists() or partial.exists():
        raise FileExistsError("AI GRIB staging target already exists")
    try:
        from ecmwf.opendata import Client
        Client(source="ecmwf", model="aifs-single").retrieve(**req, target=str(partial))
        if not partial.is_file() or partial.stat().st_size < 100:
            raise ValueError("empty AIFS download")
        with partial.open("rb") as source:
            if source.read(4) != b"GRIB":
                raise ValueError("not GRIB data")
        partial.replace(final)
        return final
    except BaseException:
        partial.unlink(missing_ok=True)
        raise

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


def parse_aigfs_index(index: str) -> list[dict]:
    """Parse NOAA wgrib2 .idx offsets; reject broken order, not just keywords."""
    records = []
    for line in index.splitlines():
        parts = line.strip().split(":")
        if len(parts) < 6 or not parts[0].isdigit() or not parts[1].isdigit():
            continue
        if not re.fullmatch(r"d=\d{10}", parts[2]):
            continue
        offset = int(parts[1])
        if records and offset <= records[-1]["offset"]:
            raise ValueError("AIGFS GRIB index offsets are not strictly increasing")
        records.append(dict(offset=offset, init=parts[2][2:], variable=parts[3].strip(),
                            level=parts[4].strip().lower(), forecast=parts[5].strip().lower()))
    return records


def matching_aigfs_records(index: str, parameter: str, run: datetime | None = None,
                           lead: int | None = None) -> list[dict]:
    if parameter not in ALLOWED_PARAMS:
        raise ValueError("unsupported AI product")
    if run is not None:
        if run.tzinfo is None:
            raise ValueError("UTC-aware initialization required")
        run = run.astimezone(timezone.utc)
    records = parse_aigfs_index(index)
    matches = []
    for record in records:
        if run is not None and record["init"] != run.strftime("%Y%m%d%H"):
            continue
        if parameter == "z500":
            if record["variable"] != "HGT" or not re.fullmatch(r"500\s*(?:mb|hpa)", record["level"]):
                continue
            if lead is not None and not (record["forecast"] == ("analysis" if lead == 0 else f"{lead} hour fcst")):
                continue
        else:
            if record["variable"] != "APCP" or record["level"] != "surface":
                continue
            if lead is not None:
                if lead < 6:
                    continue
                # Do not confuse 0-12h accumulation with 6-12h incremental precipitation.
                if not re.fullmatch(rf"{lead - 6}-{lead}\s+hour acc(?:\s+fcst)?", record["forecast"]):
                    continue
        matches.append(record)
    return matches


def has_grib_record(index: str, parameter: str, run: datetime | None = None,
                    lead: int | None = None) -> bool:
    """A unique exact record is required; duplicate APCP records are ambiguous."""
    return len(matching_aigfs_records(index, parameter, run, lead)) == 1


def _read_aigfs_index(run: datetime, lead: int, parameter: str, timeout: int) -> tuple[str, str]:
    url = aigfs_url(run, lead, parameter)
    req = Request(url, headers={"User-Agent": "MetStat-stage27-source-check/1.0"})
    with urlopen(req, timeout=timeout) as response:
        if not response.geturl().startswith("https://nomads.ncep.noaa.gov/"):
            raise ValueError("NOAA index redirected outside trusted host")
        raw = response.read(MAX_INDEX_BYTES + 1)
    if len(raw) > MAX_INDEX_BYTES:
        raise ValueError("index size limit exceeded")
    return url, raw.decode("ascii")


def probe_aigfs(run: datetime, lead: int, parameter: str, timeout: int = 15) -> dict:
    run = validate(run, lead, "aigfs")
    url, index = _read_aigfs_index(run, lead, parameter, timeout)
    matches = matching_aigfs_records(index, parameter, run, lead)
    return dict(model="aigfs", init_utc=run.isoformat(), lead_hours=lead,
                parameter=parameter, source_index=url,
                verified_index=len(matches) == 1,
                matching_records=len(matches),
                reason=("unique-record" if len(matches) == 1 else
                        "missing-record" if not matches else "ambiguous-records"),
                ready_for_publish=False)


def aigfs_byte_range(index: str, run: datetime, lead: int, parameter: str) -> tuple[int, int]:
    """Return exact indexed GRIB message bytes; last index entry has unknown length."""
    run = validate(run, lead, "aigfs")
    records = parse_aigfs_index(index)
    matches = matching_aigfs_records(index, parameter, run, lead)
    if len(matches) != 1:
        raise ValueError("missing or ambiguous AIGFS index record")
    rec = matches[0]
    i = next(i for i, r in enumerate(records) if r["offset"] == rec["offset"])
    if i + 1 >= len(records):
        raise ValueError("index cannot bound the final GRIB record")
    start, end = rec["offset"], records[i + 1]["offset"] - 1
    if end < start or end - start + 1 > 64_000_000:
        raise ValueError("invalid or oversized GRIB record range")
    return start, end


def _check_grib2_message(raw: bytes) -> None:
    if (len(raw) < 20 or raw[:4] != b"GRIB" or raw[7] != 2 or
            raw[-4:] != b"7777" or int.from_bytes(raw[8:16], "big") != len(raw)):
        raise ValueError("incomplete or invalid GRIB2 message")


def stage_aigfs_grib(run: datetime, lead: int, parameter: str, out_dir: Path,
                     timeout: int = 30) -> Path:
    """Explicit range-only staging of ONE verified-index GRIB; no upload/render."""
    import hashlib
    import json

    run = validate(run, lead, "aigfs")
    index_url, index = _read_aigfs_index(run, lead, parameter, timeout)
    start, end = aigfs_byte_range(index, run, lead, parameter)
    url = index_url[:-4]  # remove '.idx' only, preserving the official NOAA host
    req = Request(url, headers={"User-Agent": "MetStat-stage27-source-check/1.0",
                                "Range": f"bytes={start}-{end}"})
    with urlopen(req, timeout=timeout) as response:
        if not response.geturl().startswith("https://nomads.ncep.noaa.gov/"):
            raise ValueError("NOAA data redirected outside trusted host")
        if response.status != 206:
            raise ValueError("NOAA server ignored bounded Range request")
        cr = response.headers.get("Content-Range", "")
        if not re.fullmatch(rf"bytes {start}-{end}/\d+", cr):
            raise ValueError("NOAA returned an unexpected Content-Range")
        raw = response.read(end - start + 2)
    if len(raw) != end - start + 1:
        raise ValueError("truncated or oversized NOAA GRIB response")
    _check_grib2_message(raw)

    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    final = out_dir / f"aigfs_{run:%Y%m%d%H}_{parameter}_{lead:03d}.grib2"
    sidecar = final.with_suffix(".json")
    if final.exists() or sidecar.exists():
        raise FileExistsError("AI GRIB staging target already exists")
    partial = final.with_suffix(".grib2.partial")
    if partial.exists():
        raise FileExistsError("AI GRIB staging partial target already exists")
    try:
        with partial.open("xb") as fp:
            fp.write(raw)
        partial.replace(final)
        sidecar.write_text(json.dumps({
            "logical_model": "aigfs", "source_domain": "NOAA NOMADS",
            "source_run_time": run.isoformat(),
            "lead_hours": lead, "parameter": parameter,
            "index_url": index_url, "byte_range": [start, end],
            "sha256": hashlib.sha256(raw).hexdigest(),
            "state": "staged_only_requires_field_and_geometry_qc",
            "published": False,
        }, indent=2), encoding="utf-8")
        return final
    except BaseException:
        partial.unlink(missing_ok=True)
        final.unlink(missing_ok=True)
        sidecar.unlink(missing_ok=True)
        raise


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
    run = validate(run, lead, "aifs")
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

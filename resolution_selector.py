"""Deterministic same-cycle NWP resolution selection; no implicit stale-run fallback.

This module is deliberately independent of the renderer until end-to-end tests
prove that the selected source is used by downloads, QC and frame manifests.
"""
from dataclasses import dataclass
from typing import Callable, Optional

SOURCES = {
    "ecmwf": (("ecmwf_ifs", "9 km"), ("ecmwf_ifs025", "28 km")),
    "gfs": (("ncep_gfs013", "13 km"), ("ncep_gfs025", "28 km")),
}
ALIASES = {"ecmwf9": "ecmwf", "gfs25": "gfs"}


@dataclass(frozen=True)
class FieldRequest:
    model: str
    cycle: str
    parameter: str
    valid_time: str
    region: str


@dataclass(frozen=True)
class SelectedField:
    model: str
    source: str
    nominal_resolution: str
    cycle: str
    parameter: str
    valid_time: str
    region: str


def select_source(
    request: FieldRequest,
    is_valid: Callable[[str, FieldRequest], bool],
) -> Optional[SelectedField]:
    """Select the first verified field, never infer availability from config.

    is_valid must check same run, valid time, region coverage, finite values,
    grid integrity, units and physical QC. An exception is not availability.
    """
    model = ALIASES.get(request.model, request.model)
    if model not in SOURCES:
        raise ValueError(f"Unsupported logical model: {request.model}")
    if not request.cycle or not request.parameter or not request.valid_time or not request.region:
        raise ValueError("cycle, parameter, valid_time and region are required")
    for source, resolution in SOURCES[model]:
        try:
            verified = is_valid(source, request)
        except (OSError, ValueError, KeyError):
            verified = False
        if verified is True:
            return SelectedField(
                model=model, source=source, nominal_resolution=resolution,
                cycle=request.cycle, parameter=request.parameter,
                valid_time=request.valid_time, region=request.region,
            )
    return None

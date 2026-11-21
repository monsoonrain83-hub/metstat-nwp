# -*- coding: utf-8 -*-
"""Fail-closed, per-variable and per-valid-hour source policy for unified NWP.

This module does not itself download fields, render, or publish live maps.
A reader must prove same-cycle field availability, physical validity, spatial
coverage and units before declaring a source available.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

SOURCE_PRIORITY = {
    "ecmwf": (("ecmwf_ifs", "9 km"), ("ecmwf_ifs025", "28 km")),
    "gfs": (("ncep_gfs013", "13 km"), ("ncep_gfs025", "28 km")),
}
MAX_CYCLE_LEAD = {
    "ecmwf": {0: 360, 6: 144, 12: 360, 18: 144},
    "gfs": {0: 384, 6: 384, 12: 384, 18: 384},
}

@dataclass(frozen=True)
class SourceDecision:
    logical_model: str
    domain: str
    nominal_resolution: str
    variable: str
    run_utc: datetime
    valid_utc: datetime
    lead_hours: int

    def manifest(self):
        return dict(model=self.logical_model, source_domain=self.domain,
                    nominal_resolution=self.nominal_resolution, variable=self.variable,
                    init_utc=self.run_utc.isoformat(), valid_utc=self.valid_utc.isoformat(),
                    lead_hours=self.lead_hours)


def select_frame_source(model: str, variable: str, run_utc: datetime,
                        valid_utc: datetime,
                        has_verified_field: Callable[[str, str, datetime, datetime], bool]
                        ) -> Optional[SourceDecision]:
    """Select actual higher-res field first, then same-run lower-res fallback.

    The caller must validate data completeness, geography, units, and QC; never
    infer availability solely from an advertised model forecast horizon.
    """
    if model not in SOURCE_PRIORITY:
        raise ValueError("Unknown unified logical model " + repr(model))
    if not variable or run_utc.tzinfo is None or valid_utc.tzinfo is None:
        raise ValueError("variable and timezone-aware timestamps required")
    run_utc = run_utc.astimezone(timezone.utc)
    valid_utc = valid_utc.astimezone(timezone.utc)
    hours = (valid_utc - run_utc).total_seconds() / 3600
    if hours < 0 or int(hours) != hours:
        return None
    lead = int(hours)
    limit = MAX_CYCLE_LEAD[model].get(run_utc.hour)
    if limit is None or lead > limit:
        return None
    for domain, res in SOURCE_PRIORITY[model]:
        if has_verified_field(domain, variable, run_utc, valid_utc):
            return SourceDecision(model, domain, res, variable, run_utc, valid_utc, lead)
    return None

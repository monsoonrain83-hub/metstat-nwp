"""Daily anomaly temporal contract. All windows are relative to initialization UTC.

Four synoptic samples per forecast day (+6, +12, +18, +24 h), not a
continuous time integral. Five-day products are disjoint run-relative blocks.
A missing time or incompatible native grid invalidates the whole window;
a missing/non-finite cell masks that cell instead of changing sample weights.
"""
from datetime import timedelta
import numpy as np


def sample_times(run, end, days):
    if days not in (1, 5):
        return ()
    if run.utcoffset() != timedelta(0) or end.utcoffset() != timedelta(0):
        return ()
    lead = (end - run).total_seconds()
    if lead < days * 86400 or lead > 15 * 86400 or lead % (days * 86400):
        return ()
    start = end - timedelta(days=days)
    return tuple(start + timedelta(hours=6*i) for i in range(1, days*4+1))


def strict_mean(fields):
    """Mean with a fixed denominator; finite cells in every sample only."""
    total = None
    count = 0
    for field in fields:
        if not isinstance(field, np.ndarray) or field.ndim != 2 or not field.size:
            return None
        if total is None:
            total = np.zeros(field.shape, dtype=np.float64)
        if total.shape != field.shape:
            return None
        # NaN and infinity must not become zero/dry or renormalized values.
        total += np.where(np.isfinite(field), field, np.nan)
        count += 1
    if not count:
        return None
    out = (total / count).astype(np.float32)
    out[~np.isfinite(out)] = np.nan
    return out if np.isfinite(out).any() else None


def temperature_mean(series, run, end, days):
    times = sample_times(run, end, days)
    if not times or any(t not in series for t in times):
        return None
    return strict_mean(series[t][0] for t in times)


def climate_mean(climate_at, run, end, days):
    """Existing daily-normal convention: each forecast day midpoint."""
    times = sample_times(run, end, days)
    if not times:
        return None
    start = end - timedelta(days=days)
    return strict_mean(climate_at(start + timedelta(hours=24*i+12))
                       for i in range(days))

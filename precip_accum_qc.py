"""Conservative cumulative precipitation bookkeeping.

Missing increments must never become zero. An independently supplied,
same-cycle official cumulative field can re-establish the total.
"""
import numpy as np

NEG_TOL = 1e-4

def _nonnegative(a):
    a = np.asarray(np.ma.filled(np.ma.asarray(a, dtype=np.float32), np.nan), dtype=np.float32)
    return np.where(np.isfinite(a) & (a >= -NEG_TOL), np.maximum(a, 0), np.nan).astype(np.float32)

def advance_total(previous, increment, *, first_interval=False, contiguous=True, official=None):
    """Sum a valid interval or use official same-cycle totals where available.

    previous=None is only a zero baseline for the first interval from the
    actual initialization time, never for a later missing interval.
    Missing official cells may use independently valid reconstructed totals.
    """
    inc = _nonnegative(increment)
    if previous is None:
        out = inc.copy() if first_interval and contiguous else np.full_like(inc, np.nan)
    elif contiguous and np.shape(previous) == inc.shape:
        out = _nonnegative(previous) + inc
    else:
        out = np.full_like(inc, np.nan)
    if official is not None and np.shape(official) == inc.shape:
        ref = _nonnegative(official)
        out = np.where(np.isfinite(ref), ref, out)
    return _nonnegative(out)

def window_total(end, start):
    """Subtract cumulative endpoints; reject real negative/reset totals."""
    if np.shape(end) != np.shape(start):
        return None
    return _nonnegative(_nonnegative(end) - _nonnegative(start))

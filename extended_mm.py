# -*- coding: utf-8 -*-
"""Stable 60/40 blend policy for MetStat weekly and monthly model outputs.

Daily multimodel uses mm_weights.py unchanged.  This module contains no
data-source assumptions: callers must pass actual fields from the same valid
period, in the same units, on a common grid.  Never blend tercile probabilities
with numerical anomalies, and never count the NMME ensemble mean alongside its
individual members.
"""
import numpy as np

PRIMARY = {'weekly': 'ecwk', 'monthly': 'ecmwfseas'}
OTHER = {
    'weekly': ('cfswk',),
    'monthly': ('cfsv2', 'gemnemo', 'nasa', 'gfdl', 'cancm'),
}
EXCLUDED = frozenset(('iri', 'nmme', 'ecmwfseass'))
PRODUCTS = {
    'weekly': ('wpa', 'wta', 'wz5a'),
    'monthly': ('lrpa', 'lrta', 'lz5a'),
}
DEFAULT_PRIMARY_SHARE = 0.60


def weights(period, available):
    """Weight independent available models; return {} unless >=2 valid members.

    ECMWF keeps 60%, the remaining 40% is shared equally across the other
    INDEPENDENT present sources. Seasonal intentionally has no multimodel.
    """
    if period not in PRIMARY:
        return {}
    available = set(available) - EXCLUDED
    p = PRIMARY[period]
    if p not in available:
        return {}
    other = [m for m in OTHER[period] if m in available]
    if not other:
        return {}
    return {p: DEFAULT_PRIMARY_SHARE, **{m: (1 - DEFAULT_PRIMARY_SHARE) / len(other) for m in other}}


def blend(period, fields):
    """Weighted anomaly (or precipitation rate) from real, aligned 2-D grids.

    The caller is responsible for matching valid dates, baselines, units, and
    regridding *before* this method.  A result cell is NaN unless ECMWF and at
    least one other independent source both have finite data there.  Returns
    (array, weights) or (None, {}) if fewer than two models are available.
    """
    if period not in PRIMARY:
        return None, {}
    w = weights(period, fields.keys())
    if not w:
        return None, {}
    p = PRIMARY[period]
    shape = np.asarray(fields[p]).shape
    if len(shape) != 2:
        raise ValueError('Multimodel fields must be regridded 2-D arrays')
    for key in w:
        if np.asarray(fields[key]).shape != shape:
            raise ValueError(f'Non-identical grid for {key}; regrid first')
    A = np.stack([np.asarray(fields[m], dtype=np.float64) for m in w], axis=0)
    valid = np.isfinite(A)
    # Keep ECMWF at EXACTLY 60% in every supported cell. If an alternative
    # model is missing locally, redistribute the OTHER 40% amongst the
    # remaining alternatives, not back to ECMWF.
    ow = np.array(list(w.values())[1:], dtype=np.float64)[:, None, None]
    other_weight = np.sum(valid[1:] * ow, axis=0)
    other_sum = np.sum(np.where(valid[1:], A[1:], 0.0) * ow, axis=0)
    supported = valid[0] & (other_weight > 0)
    other_mean = np.zeros(shape, dtype=np.float64)
    np.divide(other_sum, other_weight, out=other_mean, where=other_weight > 0)
    out = np.where(supported, 0.6 * np.where(valid[0], A[0], 0.0)
                   + 0.4 * other_mean, np.nan)
    return out.astype(np.float32), w

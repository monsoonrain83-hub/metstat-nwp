# -*- coding: utf-8 -*-
"""Minimum structural QC for real fields entering the daily MetStat MultiModel.

This is a *guard*, not meteorological validation or resampling. It cannot
establish unit correctness, same-cycle provenance, native grid geometry,
spatial coverage of the advertised region, or DEM conservation. Those
checks belong in the producing model's source/QC manifest.
"""
from __future__ import annotations

import numpy as np


class MultiModelFieldError(ValueError):
    """An invalid or non-comparable model field must never be blended."""


def prepare_field(field, *, min_fraction: float = .01) -> np.ndarray:
    """Return a 2-D float32 field, preserving masked cells as NaN.

    The caller may set min_fraction=0 for sparse *categorical alerts*, but
    at least one finite pixel is still required.
    Finite zero-valued precipitation is legitimate. Entirely absent or
    effectively empty arrays, infinities and unexpected shapes are not.
    """
    if not 0 <= min_fraction <= 1:
        raise ValueError("min_fraction outside [0, 1]")
    try:
        masked = np.ma.asarray(field, dtype=np.float32)
    except (TypeError, ValueError, OverflowError) as exc:
        raise MultiModelFieldError("non-numeric field") from exc
    if masked.ndim != 2 or min(masked.shape) < 2:
        raise MultiModelFieldError("model field is not a nontrivial 2-D grid")
    arr = np.asarray(np.ma.filled(masked, np.nan), dtype=np.float32)
    if np.isinf(arr).any():
        raise MultiModelFieldError("field has infinite values")
    finite = np.count_nonzero(np.isfinite(arr))
    if finite == 0 or finite / arr.size < min_fraction:
        raise MultiModelFieldError(
            f"insufficient finite grid cells: {finite}/{arr.size}"
        )
    return arr


def validate_blend_payloads(payloads: dict, *, min_fraction: float = .01) -> tuple[int, int]:
    """Reject incompatible saved source grids before begin/render/upload.

    Each source is keyed by its independent logical family, not by both
    ECMWF/GFS source resolutions. Invalid optional contour/wind arrays
    must not bring down the renderer after a manifest was begun.
    """
    if not payloads:
        raise MultiModelFieldError("no staged physical models")
    shape = None
    for name, data in payloads.items():
        if "f" not in data:
            raise MultiModelFieldError(f"{name}: missing scalar field")
        checked = prepare_field(data["f"], min_fraction=min_fraction)
        if shape is None:
            shape = checked.shape
        if checked.shape != shape:
            raise MultiModelFieldError(
                f"{name}: grid mismatch {checked.shape} versus {shape}"
            )
        for key in ("c", "bu", "bv"):
            if key not in data:
                continue
            candidate = np.asarray(data[key])
            if candidate.shape != shape or not np.issubdtype(candidate.dtype, np.number):
                raise MultiModelFieldError(f"{name}: invalid {key} grid")
            if np.isinf(candidate).any():
                raise MultiModelFieldError(f"{name}: infinite {key} cells")
    return shape


def pixel_weights(fields: np.ndarray, slots: list[str], weights: dict):
    """Keep ECMWF at 60% on each valid cell; renormalize peers within 40%.

    The pre-existing ECMWF/GFS core requirement is enforced per pixel.
    Missing core data remains NaN in the final field. Optional peer gaps
    cannot transfer any of the ECMWF share or create a single-model blend.
    Metadata weights describe nominal participating families.
    """
    if len(slots) != len(set(slots)) or 'ecmwf' not in slots or 'gfs' not in slots:
        raise MultiModelFieldError("missing or duplicate core families")
    if set(slots) != set(weights) or not np.isclose(weights['ecmwf'], .6):
        raise MultiModelFieldError("invalid nominal family weights")
    base = np.array([weights[m] for m in slots], dtype=np.float64)
    if not np.isfinite(base).all() or (base <= 0).any() or not np.isclose(base.sum(), 1):
        raise MultiModelFieldError("invalid weight vector")
    valid = np.isfinite(fields)
    ec, gf = slots.index('ecmwf'), slots.index('gfs')
    mask = valid[ec] & valid[gf]
    w = base[:, None, None] * valid
    w[ec] = 0
    total = w.sum(axis=0)
    w *= np.divide(.4, total, out=np.zeros_like(total), where=total>0)
    w[ec] = .6
    w *= mask
    return w, mask

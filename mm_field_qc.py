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

    Finite zero-valued precipitation is legitimate. Entirely absent or
    effectively empty arrays, infinities and unexpected shapes are not.
    """
    if not 0 < min_fraction <= 1:
        raise ValueError("min_fraction outside (0, 1]")
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
    if finite / arr.size < min_fraction:
        raise MultiModelFieldError(
            f"insufficient finite grid cells: {finite}/{arr.size}"
        )
    return arr


def validate_blend_payloads(payloads: dict) -> tuple[int, int]:
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
        checked = prepare_field(data["f"])
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

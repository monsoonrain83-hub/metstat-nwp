# MetStat Stage38 — pre-publish MultiModel field QC and NPZ resource safety

**UTC:** 2026-11-24  
**Branch:** `fix/stage38-mm-field-qc-before-publish-20261124`  
**PR:** https://github.com/monsoonrain83-hub/metstat-nwp/pull/35  
**Base:** `feat/stage27-mm-180h-fixed-ecmwf60` (draft PR #33), **not main**  
**Status:** executable draft only, no live publication, no cPanel changes.

## Observed producer weaknesses

The actual `mm_maps.py` in PR #33:
- Wrote incoming scalars directly to .npz without checking numeric 2-D shape or effective NaN coverage. A malformed high-resolution source could be registered as available and win over valid lower-resolution fallback.
- Called `begin(run)` before confirming that staged ECMWF/GFS/peer fields, contours and barbs share the render grid shape. A mismatched source could therefore break the blend after starting host publication.
- Loaded `np.load(...,allow_pickle=False)` without a context manager, risking open NPZ file descriptors during large runs.

## Changes

`mm_field_qc.py` provides two explicit guards:
- `prepare_field`: float32 2-D grid, masked pixels converted to NaN, reject Inf, non-numeric and entirely missing fields. For **continuous** products, at least 1% finite cells; zero rain is valid and is **not** treated as missing.
- For **sparse categorical secondary warnings/hazards** (`kind='sec'`), a single finite grid cell is sufficient; no blanket 1% cutoff. This prevents erasing a legitimate highly localized warning. An all-NaN warning is still rejected.
- `validate_blend_payloads`: all model field and optional 2-D contour/barbs must have the **same shape**, otherwise hard-fail before uploader `begin`. No hidden interpolation or change of physical values.

`MMCombiner.sink` invokes QC before staging or indexing the field; `MMCombiner.make` invokes grid QC before `begin`; `MMCombiner.load` closes the NPZ handle using `with np.load(...)`.

## Tests and CI

File `tests/test_mm_stage38_field_qc.py` covers:
- valid zero precipitation, masked inputs and numeric conversion;
- reject wrong dimensions, nonnumeric, infinity, all NaN and near-empty continuous fields;
- accept real one-pixel secondary hazard, reject all-NaN secondary hazard;
- reject mismatched scalar, contour and wind grid shapes;
- **source fallback after rejected ECMWF high-res**: only verified lower-res ECMWF is chosen, on the same cycle and valid time;
- prevent `begin(run)` on incompatible two-model NPZ arrays;
- assert staged NPZ loader closes the handle on exit.

The `quality-nwp` workflow already includes `tests/test_mm_*.py`, Python lint/security checks, offline mock NWP production and world/anomaly regression checks. A passing workflow proves the **offline test suite**, not real meteorological source quality or host publication.

## Scientific boundaries

**Not proven by Stage38**: source grid coordinate alignment (a same-shape field can have a different CRS or origin), source units/accumulation periods, actual-cycle provenance, worldwide geographic coverage, native 9/13/28 km resolution, model field calibration, 60/40 weights in cells with missing contributions, or DEM water conservation. The real source-to-published-frame manifest must validate these separately.

The 1% continuous-field threshold is a basic sanity guard, not geospatial completeness. Do not merge as "global data QC complete". No fallback to an older run is permitted by this patch, and no meteorological formula was replaced.

## Deployment and integration

1. Review/finish PR #33 (+180h, ECMWF 60%, GFS/peers 40%), confirm base HEAD and no branch conflicts.
2. Run all Stage38 and existing NWP tests, inspect genuine full-field source shape + geography + masks for each family and region; compare before and after completeness metrics.
3. Verify chosen high/low resolution, init UTC, valid UTC, lead, native grid and units **for each resulting field** in manifest.
4. Do not publish to cPanel until a real NWP run completes, all required frames are accounted for, on-host route responds 200, GIS/PNG/GIF smoke passes, backup/rollback is possible and administrator approves.

**No cPanel ZIP is supplied for Stage38:** this stage modifies the GitHub-side NWP producer, not the current active host files. Stage37 host overlay and all previous index SHA installation restrictions remain independent.

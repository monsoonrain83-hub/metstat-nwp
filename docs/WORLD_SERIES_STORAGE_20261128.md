# World NWP — multi-lead storage, 1405-09-07

## Scope
Priority NWP-02/03/04 and storage aspect of NWP-08. This is an isolated
candidate; not the production uploader, not cPanel deployment and not
a claim of real 360/384-hour source availability. Existing world-data
and Iran/ME assets are unchanged.

The input is a series.json inventory and exact per-lead native raster
manifests produced by global_nwp_series.py. An independently provided
required-leads policy must match the inventory. All three existing
baseline variables are required. No nearest lead, other initialization,
placeholder, or missing baseline variable is accepted for this store.

Example (only on a dedicated local POSIX test directory, not public_html):

    python pack_global_series.py --src review/gfs --root review-store --model gfs --required-leads 24 240 360 384 --max-bytes 500000000 --reserve-bytes 500000000

The example lead list is a probe subset, not the final product cadence.
The byte values are illustrative operator limits, not measured host capacity.
max-bytes is per model and includes the peak before old-run removal.
reserve-bytes is a free-disk floor, not a full multi-process quota.
Use a different dedicated store when the required lead plan changes.

## Layout and safety
root/model/catalog.json is the only visibility pointer. Its runs array
contains at most the two newest accepted initializations. Each directory
has a run.json and fNNN/{t2m,z500,mslp}.webp. Paths in run.json are relative
to that immutable run directory. Original source-domain metadata,
resolution, run, valid time, checksum and licence are preserved.

A local flock serializes writers for each model. A complete candidate
is verified and staged on the same filesystem before the pointer is
atomically replaced. A prior catalog's third-oldest run is removed only
after the new pointer is synced. Unknown directories are not removed.
Do not put permanent archives inside a managed run directory. Disk space
is checked before publication; failure does not trigger old-run pruning.
If a process crashes after installing a candidate but before updating the
pointer, an unreferenced directory can remain; investigate manually.
A pruning error after publication can leave extra old bytes and must be
reported and reconciled, not automatically sweep unrelated files.

## Verification
Eight new offline storage tests use generated WebP fixtures, not
meteorological observations. The separate read-only GitHub workflow runs
these and prior series tests, without secrets or publication. Full live
integration, host upload transaction, concurrent reader behavior and
server quota still require verification. Existing single-lead catalog
compatibility and model-specific real lead availability remain open.

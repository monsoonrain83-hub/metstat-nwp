# V106 — World extent rollout (retrieved and updated user contract)

This supplements METSTAT_HANDOVER_1405-09-05_V88.md and the V105 requirements.
The newest explicit user instruction supersedes the earlier ME-only AIFS/AIGFS
and ARPEGE regional limits, and supersedes any plan to calculate H/L on anomaly values.

## Target products and UI
- Genuine globe coverage for ECMWF (9 km primary, 28 km fallback) and GFS
  (13 km primary, 28 km fallback), plus ICON, UKMO and GEM/GDPS. One display
  model per logical family, per-parameter/lead selection with the actual
  native source and resolution in each frame's metadata. Never mix cycles.
- Main models: surface precipitation 1/3/6/24/48/120h and run total where
  supported, T2m and validated Tmin/Tmax, RH2m, MSLP, 10m winds/gusts;
  Z, T, RH, wind at 850/700/500/300/200 hPa when actually available.
  User approval (2026-11-26): global convection and Significant Weather
  for these five logical families ONLY, where verified native fields permit:
  CAPE, CIN, LI, K, TT, GDI, Soaring, Showalter, SWEAT, KO, lapse rates,
  wind shear, simulated reflectivity and existing Significant Weather.
  Preserve existing formulas and distinguish native from derived fields.
  Check pressure-level availability, same-cycle/grid consistency, units,
  below-ground masks and missing values. No invented inputs or model mixing.
  Regional hazard forecasts (flood, hail, lightning and severe-weather
  warnings) retain their current extent and calibration. Other specialized
  fields, including snowfall, retain existing regional coverage unless
  separately approved.
- AIFS, AIGFS, Google GraphCast/WeatherNext (do not double-count aliases),
  France ARPEGE, Japan, China and Korea: true global coverage for pacc,
  p24, T2m, Z500a first; only verified source fields, access/licence and
  accumulation semantics. Preserve existing independent model behavior.
  No convection or Significant Weather products for these new models at
  this stage. Their first-phase four-product scope remains unchanged.
- Z850a/Z700a/Z500a/Z300a/MSLP anomalies at available 6-hour frames;
  H/L on absolute pressure or height, existing detector/colors/values;
  T2m daily and independent five-day windows unchanged.
- Geographic hierarchy in one horizontal row: continent/world, region,
  country, province, county. Country/region availability must be based on
  real data extent. Existing ME/EU/Iran products and archived links stay intact.
  Capital points/labels independent, scalable labels, thicker county borders,
  full-boundary fit, fixed PNG output geometry.
- No invented global coverage, no display of regional images beyond their
  actual bounding box, no fake model menus. True WGS84 geometry including
  dateline and polar limits. Keep processing off cPanel and budget storage.
- Same existing DEM correction once for precipitation wherever real DEM
  and model terrain cover the same cells. Never extrapolate Iran DEM
  globally or apply a second correction. Validate precipitation interval,
  zero/missing distinction, conservation, units, and source provenance.

## Current verified state, 2026-11-26
Existing world-data/world/catalog.json (blob 3df4c65dfa7b9f7795e7416d2e5fc3af046dcb99)
lists five families with valid +24h products: ECMWF, GFS, ICON and UKMO
have t2m/z500/mslp; GEM has t2m/mslp. Runs vary by family; each individual
frame has its own run/valid time. This is a retrieved source catalogue,
not independent verification of raster bytes during this turn.
The old schema-1 catalog is a single frame per field and remains operational.
The archived main host does not include a /world/ directory; no current
live host world deployment was proven. Do not confuse the standalone
world viewer with completion of the integrated main forecast page.

## This change
- global_nwp_stage.acquire optional required_run pins the exact source
  cycle. Existing one-lead stage remains backward compatible.
- pack_world_frames.py produces schema-2 multiframe release from
  independent verified frame artifacts; one run per model, sorted
  valid times, actual SHA, immutable image paths, byte budget (512 MiB
  staging default, configurable), duplicate/mixed-cycle rejection,
  unavailable models reported; never marks a partial release complete.
- First phase currently accepts the existing t2m/z500/mslp stage only;
  new field contracts, scientific provenance and precipitation DEM
  pipeline must be implemented before admitting additional products.
- Offline regression passed quality-nwp run 45882301377. Existing
  global workflow and data branch are not replaced. Main remains unchanged.

## Deployment gates
1. Real multi-frame acquisition using exact same cycle per family.
2. New world field coverage and accumulation/reference/DEM validation.
3. Main viewer reads the validated catalogue only when real world frames
   exist, retains regional views and current model IDs. Test map geometry,
   model/run/frame selection, geog hierarchy, export and browser lifecycle.
4. Verify actual host baseline, storage, upload integrity, two-run retention,
   rollback and live public map readback. Only then install/publish.

## V107 — global convection first implementation (staging only)
- Opt-in `global_nwp_stage.py --convection`: CAPE, CIN, LI, K, Soaring,
  TT, GDI, Showalter, 700–500/850–500 lapse rates, 850–500 shear and
  existing 10 m–500 hPa approximate 0–6 km shear. Derive each product on
  one native source and same cycle/valid time. Use existing MetStat
  thermodynamic kernels and discrete palettes. Reject incompatible
  grids/units, mask below-ground levels (15 hPa margin); no Iran-specific
  surface substitution for global indices. Existing native CAPE/CIN/LI
  are preferred; CIN requires negative convention. Pressure derived
  from MSLP and native terrain is identified as approximate.
- Global raster verifier now accepts these twelve products only with
  explicit units, palette and input/calculation provenance.
- Real data acceptance workflow `v107-world-convection-probe.yml`
  reads one +24 h frame per core model, max parallel 2, job 35 min,
  staging budget 128 MiB/model, no secrets, no write to host or data
  branch. Missing products are reported explicitly.
- SWEAT, KO, simulated reflectivity, Significant Weather, full-profile
  shear and remaining indices are pending. In particular reflectivity
  and SigWx require verified precipitation interval/phase semantics;
  do not turn a cumulative precipitation field into a rate blindly.
- Real field coverage, native unit documentation and scientific QA,
  complete world timeline and main forecast UI integration remain release
  gates. No change to regional formulas or operational publishing.

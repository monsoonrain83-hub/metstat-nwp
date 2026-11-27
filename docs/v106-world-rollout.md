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

## V108 — real coverage and remaining weather indices

V107 completed quality-nwp and P0 host synchronization checks at cfbf31602949c11df4ad91ca37fe7f91fc1cade6 (runs 45885755691 and 45885755756).
Real acceptance 45885750100, same 2026-11-26 12Z initialization and +24h:
ECMWF cape/li/lr75/sh06; GFS cape/li/lr75; ICON cape/li/lr75/sh06;
UKMO cape/cin/li/lr75; GEM no convection output (t2m/mslp only).
This establishes real production of a subset, not complete five-model coverage.
- KO and SWEAT reuse existing MetStat surface-based KO and modified SWEAT
  equations; same native input source and terrain masks; parity regression.
- Reflectivity and SigWx stage only when the exact source completed
  latest.json identifies the previous native timestamp in the same run.
  Open-Meteo open-data README documents native timesteps and backward
  precipitation sums: https://github.com/open-meteo/open-data#updates-to-real-time-weather-forecasts
  No fixed six-hour divisor, no borrowing older cycles, no zero-filling.
  Existing native rate diagnostic is not DEM-adjusted precipitation.
  White = clear/no echo; gray = missing; phase approximation explicitly
  recorded. SigWx requires CAPE, surface temperature/RH and wind;
  ice phase availability recorded. These are not official hazard warnings.
- The world stage now records per-source input presence/range/finite
  coverage and low-valid-fraction rejection. Diagnosing GEM missing
  fields and validating official ECCC GRIB metadata, grid and units are
  still necessary; do not silently reuse unverified regional decoding.
- V108 completed-cycle single-lead probe tests both weather and convection
  modules before staging; no host/data-branch writes. New CI and real
  acceptance pending at this entry. Main, old world catalogue, regional
  products and host remain unchanged. DEM/precipitation global products,
  main viewer integration and complete forecast timeline remain gates.

## V109 — terrain-aware quality gate and exact-run timeline
V108 quality-nwp 45886723787, P0 45886723800, and real acceptance
45886681213 passed. Verified +24h staging coverage (runs 2026-11-26):
ECMWF: cape,li,lr75,sh06,refl,sigwx; GFS: cape,li,lr75,refl;
ICON: cape,li,lr75,sh06,refl,sigwx; UKMO: cape,cin,li,lr75,refl,sigwx;
GEM: refl only among convection/weather. All also produced some basic fields.
ECMWF and UKMO used 06Z; other three used 12Z. GEM pressure inputs
were absent in the tested Open-Meteo file, not proven absent in GDPS.
GFS/ICON/UKMO K/TT/GDI rejection was largely the flat 90% global grid
coverage threshold versus physically below-ground pressure levels.
- Count terrain-excluded, unknown-pressure and valid cells separately.
  Require 90% of cells not explicitly excluded by known terrain pressure,
  with unchanged 15 hPa margin; unknown pressure remains missing.
  Conservative maximum exclusion 30% of grid cells (engineering gate,
  not a scientific threshold). Unmasked products retain the old 90%
  rule. Validate count consistency and expected product/level mapping.
  Do not convert positive-source CIN to negative until source semantics
  are verified, nor silently clip source RH or mix high/coarse fields.
- Six new terrain tests; quality-nwp 45930221590 and P0 45930221834
  passed at 793fefb144f6773ab105aba9dc73866a3f0358ce.
- Real two-lead +24/+48h staging workflow 45930216371, exact cycle
  pinned from first manifest, 128 MiB/model staging budget, no deployment.
  Pending at time of entry.
- New independent official ECCC GDPS 15 km GRIB reader
  world_gem_official.py checks single-message size, time, level,
  variable, explicit units, global regular grid and orientation.
  Official source documentation:
  https://eccc-msc.github.io/open-data/msc-data/nwp_gdps/readme_gdps-datamart_en/
  Bounded fixed-source downloads, no cross-source field merge.
  Unknown/grid-relative winds are rejected until orientation verified.
  Five metadata fixture tests and separate official read/derive
  acceptance 45930380359 pending. Official reader is not yet admitted to
  publication catalogue; verify actual names/metadata/access/licence
  and results first. Regional engine unchanged.
- Host integration, actual DEM corrected global rainfall and reference
  climatology remain open. No host release or live deployment in V109.

## V110 — mandatory single host publication root
User instruction: ALL current and new model products must use existing
`public_html/online/data/` only. Canonical model frame path:
`online/data/nwp/<logical_model>/<run>/<region>/<parameter>_<valid>.webp`.
World is a region named `world` alongside iran/fars/me/eu. The only
operational index is `online/data/manifest.json`; no separate public
/world directory or parallel live model catalog. Temporary CI artifacts
and GitHub world-data are staging only, not a second host store.
Keep existing weekly/monthly/seasonal paths within online/data.
Do not delete/relocate existing host files until verified migration.
- Inspected the actual archived online/nwp_upload.php, SHA256
  4b57c03a5498194efeec5bafc7a4a8e11885da7529563c3232d6f1ed10dcc9f9.
  It is newer than repository root nwp_upload.php (per-model lock,
  batching, compressed manifest, atomic writes). Never replace it with
  the older repository copy.
- Local candidate builds from this exact archive, adding worldput-v1 and
  worldsync-v1 to the existing authenticated endpoint, same per-model
  lock/state/manifest. Current model and exact current run only; no begin,
  purge, creation of a parallel model or advancement of the regional run.
  Immutable filename conflicts fail closed, same digest retries succeed.
  Verify source, parameter, time, geometry, WebP, digest, terrain coverage
  and weather interval; preserve old current/previous regional frames.
  World sync rebuilds existing manifest once, not after every upload.
  Local PHP HTTP test with real V108 ECMWF CAPE bytes passed 29 checks.
- `plan_world_host.py` is an offline canonical destination planner,
  not a live uploader. It defers current host run mismatch, unregistered
  products and incompatible scales. Initial scope: existing convection
  IDs on five core models, exact existing model state. All new models
  later use same root, via approved catalog onboarding, not a second tree.
- IMPORTANT: existing regional z500 is a RH background with height
  contours, not a standalone height raster. Existing regional t2m uses
  its fixed palette, unlike the old world-stage generic palette. Do not
  register these experimental raster variants under existing product IDs
  before harmonizing product definitions and palette. UI must understand
  world EPSG:4326 raster metadata and geographic crop before deployment.
- Local candidate is not a host install release. Actual host hash,
  integrated browser renderer, multi-run publication and retention,
  storage budget and readback must pass before production activation.
  Existing scheduled regional producer and all live files unchanged.

## V111 — producer-first ingestion (explicit user decision)
All current and future NWP models must extend the existing canonical
`public_html/online/data/nwp/` tree, model IDs, run directories and shared
`online/data/manifest.json`. World is only an additional geographic region
of the same model. Do not create a second operational model store or a
parallel publication system. Existing regional paths and two-run retention
remain intact; any code needed for world products belongs to the same
operational NWP ingestion/render/publish pipeline, not a new live website.
Offline CI staging is not an alternative public store.

Source policy, applicable to every existing and new model:
1. Attempt the original producing center's official open-data service,
   documented API, or producer-published official distribution first.
2. Use an authorized intermediary (e.g. Open-Meteo data_spatial) only when
   that requested product/grid/lead is not available or cannot be
   legitimately retrieved from the producer after bounded checks.
   Do not bypass access controls, terms, licensing or rate limits.
3. Preserve existing ECMWF 9 km / GFS 13 km priority over coarse fallback
   within the previously agreed resolution policy: check official delivery
   for the requested resolution first, then eligible intermediary for that
   resolution if needed. No silent resolution downgrade or fake upsampling.
   Record actual native/effective resolution and the fallback reason.
4. The exact initialization, validity, accumulation interval, grid, units,
   product/level and physical semantics must agree. Derived fields must
   use a coherent input bundle; do not blend unrelated distributions,
   grids, model variants or cycles to fill gaps. Reject unverified values.
5. Record producer, distribution/access tier, actual source identifier,
   source timestamp, model variant, licence/attribution, grid, native
   resolution and fallback reason in frame provenance. Reuse the same
   validated official inputs for all compatible products at that frame.
   Prefer bounded downloads, shared cache and product-level availability.
   No speculative URLs or claims that a center exposes a specific field.
6. Original center candidates to validate: ECMWF Open Data (IFS/AIFS),
   NOAA/NCEP (GFS/AIGFS), DWD (ICON), ECCC/MSC (GDPS), UK Met Office
   (UKMO), Météo-France (ARPEGE), JMA, CMA, KMA, and Google official
   WeatherNext/GraphCast distribution where applicable. These are source
   candidates, not a claim of verified access to every parameter.
   New AI/national models retain four-product first-phase scope and no
   convection or Significant Weather. Five core families retain the
   approved global convection scope.

Evidence already available: V109 official ECCC probe 45930380359 passed,
17 meteorological input fields and terrain verified, 11 derived convection
products calculated independently from official GRIB2. V109 two-lead
acceptance 45930216371 passed for five families (+24/+48h). Official ECCC
is the first verified direct-source adapter to integrate into the common
NWP pipeline; existing fallback remains available until equivalent
products, provenance, geometry, licence and host regression are proven.
No new operational deployment is authorized by this documentation alone.

## V112 — official GDPS in the shared global staging pipeline
- global_nwp_stage now attempts official ECCC GDPS first for the exact
  selected GEM initialization and valid hour. Original GRIB2 is decoded by
  the previously verified reader. Existing global rendering/terrain QC
  and thermodynamic kernels are reused. Completed products are not
  overwritten by Open-Meteo. Derived products use a single distribution
  and native grid. Intermediary fallback for unavailable/unverified
  products is recorded separately. Other models explicitly report that
  their official adapter has not yet been validated.
- Per-field original source URLs, input records, producer, distribution
  tier, ECCC licence link and attribution are preserved. The common
  packager now verifies official field dependencies, exact URL identity
  for the requested time, GDPS grid and licence. Both distributions use
  the same GEM model key and canonical online/data/nwp deployment plan.
- ECCC End-use Licence v2.1.1 (August 2026):
  https://eccc-msc.github.io/open-data/licence/readme_en/
  Preserve required data-source attribution in final maps/UI.
- Three fixture tests, dedicated real two-lead integrated acceptance
  workflow v112-gem-producer-first.yml. At time of entry tests pending.
- Limits: cycle discovery still uses existing Open-Meteo metadata,
  official native precipitation interval not yet implemented, and GEM
  operational regional ingestion/host uploader not switched. Official
  URLs/metadata are validated for staging only, not an assertion of
  full production coverage. Host uploader must admit original source
  provenance before release, and the primary viewer must render these
  global products correctly. Other official adapters (ECMWF/NOAA/DWD/
  UKMO and new models) remain pending. No second public tree or live
  publishing; do not change existing schedule/retention.

## V114 — post-model release geography and R5 acceptance (user priority)
First finish usable, tested model publication and host deployment through
the existing online/data/nwp tree. Next implement shared geographic navigation
in the forecast viewer (normal, fullscreen, professional) and synergy.
No substitute mock website or copy of the R5 demonstration engine.
- Semantic hierarchy: globe -> continent -> country -> ADM1 (province/state)
  -> ADM2 (county/equivalent). Stepwise zoom-out is the exact inverse.
  Preserve existing Middle East and Europe/north Caspian preset extents
  and their boundary/label layers. Regional preset menu remains available.
- Globe: label major oceans and continents. Continent: country labels.
  Country: ADM1 labels. ADM1: ADM2 labels. Point symbols and place names
  follow the same hierarchy and established independent visibility toggles.
  Use verified names, parent IDs, true geometry and interior label anchors,
  not fabricated admin levels or arbitrary rectangular selections. Handle
  countries without ADM2 explicitly, preserve existing Iranian boundaries
  and national cartographic conventions. Global administrative datasets
  require verified licensing, accuracy and boundary policy before deployment.
- Clicking the map, plus/minus icons on the map and dependent geography
  menus above the map all use the same hierarchical state and transitions.
  Preserve selection when switching display modes; no duplicate controls.
  Distinguish dragging/drawing/inspection from click-to-zoom; no skipped
  level on plus/minus; menus synchronize ancestors and descendants.
  Collision/priority-aware labels, scale-aware boundaries and points,
  viewport culling and lazy per-country geometry loading. Do not download
  all ADM2 geometry on initial page load. No new live model store.
- R5 visual reference: user attachment OPEN_METSTAT_R5_ANDROID_FIXED(1)(1).html
  SHA256 2792e674660f07135acb91f6cbf92f8740f4c9ff8c073e94767927b1c8dbadf9.
  Actual reference inspected: desktop-first RTL, min width 960 in portrait,
  compact two-column landscape, Sky #399FD4 / Paper #F8F9FD / Scarlet #DC1937,
  five geographic selectors (geoContinent, geoRegion, geoCountry,
  geoProvince, geoCounty), independent colored status markers, overlay
  drawing/layer tools, palette/timeline/export controls, seven nav families.
  Reference is an offline demo (connect-src none, sample state). Port
  applicable visual/interaction details into actual site routes and engines;
  never replace real authentication, data, routes or forecast functions
  with demo code. Retain prior guest policy and horizontal existing model
  buttons in fullscreen (user instruction overrides reference placement).
- Acceptance: actual browser and device tests of all three zoom entry
  paths, reverse hierarchy, label priority, normal/fullscreen/pro/synergy,
  regression of existing ME/EU/Iran/Fars/county and export behavior.
  Finish complete R5 audit after usable model release, not before.

### V114 implementation evidence
- V112 real integrated official GDPS workflow 45932713613 passed:
  fourteen official products at BOTH +24 and +48 h, including eleven
  convection products; reflectivity via separately verified intermediary.
- V113 full browser replay completed on 1440x900 and touch 390x844,
  archived 56,548-row manifest with isolated same-run fixture insertion,
  actual ECMWF CAPE 24/48h WebP loads, original viewer menus, square-map
  export 954x1300 canvas and return to Middle East. No page errors.
  This is an offline replay, not a live host test; archived regional
  images were not replayed. The earlier timeout is resolved in replay.
- Local V114 integrated candidate extends the archived uploader version,
  admits original ECCC GDPS only with exact source URL, grid, lead and
  attribution verification. Local 37 PHP HTTP assertions passed with real
  V108 ECMWF and V112 GEM images. Corrected world subtitle resolution and
  official attribution display. Preserve only bounded source descriptors
  in shared public manifest; complete input provenance remains in staging.
  Final V114 browser replay and current host baseline/readback still
  required. No live writes or second data directory.

## V115 — host publication client and installation readiness
- Existing public HTTPS root exact SHA256 confirmed V105
  82cd6d47ff38b03d5fffc5051bafcf16ebe4842b9f410babb99e64062cbb1b8e
  in site repository read-only workflow 45936123665. FTPS connection
  failed certificate verification (SSLCertVerificationError); no
  insecure TLS fallback. Current online/nwp_upload.php hash is NOT
  verified. Request only that file from administrator, never config/key.
- Frontend-only package MetStat_V115_frontend_upload.zip
  SHA256 72158ce033f52332643e953c33fb66ec1968d2c1db7b05efc2b98835459af5cb,
  five exact tested V114 UI files. No PHP/data/auth/config replacements.
  Compatible with confirmed V105 index baseline. World menu remains
  availability-gated; installing UI alone will not create live world data.
- publish_world_host.py (commit 98df05780ed91fd59f741ca96b848d89052b5bb8):
  explicit apply only; fixed HTTPS origin, no redirects, no key logging,
  bounded plan preflight, exact same current model run, capability
  checks, upload limits, acknowledge each SHA, sync common manifest
  and verify public raster bytes. Never call begin/end/purge. No atomic
  all-model batch transaction; partial upload can occur on interrupted
  request, safely retry same immutable bytes while run remains current.
  Local end-to-end replay against actual candidate PHP, four genuine
  ECMWF CAPE and official GEM K-index frames, 17 checks passed.
- Existing nwp.yml now contains opt-in world job (commit
  576585bd6b5d9549498a391b2a3810048b9ee6c8). Disabled by default
  unless METSTAT_WORLD_ENABLE=1; no change to existing cadence or
  regional jobs. First tranche two leads (+24/+48) per core family,
  one model at a time, 128 MiB/model, exact current host cycle. Uses
  existing MX_KEY only in explicit publish step; no second live store.
  Full timeline, base products, reference climate, other direct
  adapters, geography and R5 remain open. Branch not merged or live.
- V114 browser_v114_report confirms both desktop and mobile offline
  end-to-end viewer replay, zero page errors, actual V109 ECMWF images.
  Full combined live deployment pending current uploader hash and
  authenticated installation verification. Do not claim site world
  coverage is live from these tests.

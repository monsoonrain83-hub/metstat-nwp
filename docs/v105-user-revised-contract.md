# V105 — updated user requirements (supersedes V104 daily-height plan)

- Height anomalies Z850/Z700/Z500/Z300 and MSLP anomaly: exact 00/06/12/18 UTC forecast frames, only if actual field and matching 1991–2020 reference exist; no daily height averaging. T2m daily and independent five-day windows unchanged. No historical data removal.
- Signed anomaly centers H (positive/red) and L (negative/blue) are a separate WebP overlay with parameter suffix AH; original absolute-pressure/height H overlays are unchanged. Existing archived host uploader accepts the filename and skips separate catalogue entries for H-ending overlay files. Full host upload/export verification still required.
- Reference per parameter: data/static/era5_synoptic_1991_2020_{parameter}.npz and .npz.json. NPZ: lat, lon, field (366,4,nlat,nlon), hours 00/06/12/18. JSON schema=1, source=ERA5, base_period=1991-2020, temporal_basis=synoptic_6h, calendar=366_month_day, hours_utc=[0,6,12,18], parameter, units (m/hPa), sha256. Reference must be built from verifiable upstream data; no fabrication or relabeling. NCEP-NCAR Reanalysis 1 4x/day 1991–2020 is a separately identified alternative (365-day calendar, interpolate Feb29 at same hour), not a silent substitution. Existing WeatherBench2 cache is 1990–2019.
- UI: independent capital point/name toggles; province-dependent county selection; scalable labels; thicker county boundaries; tight geographic fit with fixed original PNG aspect/dimensions. Frontend candidate is separately tested; no automatic host writes.

## Global-source onboarding

| Candidate | Source route to verify | Status |
|---|---|---|
| ECMWF AIFS Single | ECMWF Open Data / Open-Meteo AIFS | raw sample and grid/precip interval validation pending |
| NOAA AIGFS | NOAA NOMADS / AWS open data | same-cycle raw GRIB and accumulation validation pending |
| Google GraphCast / WeatherNext | official Google data access | access/licence, current run and precipitation fields pending; don't count an alias twice |
| France ARPEGE global | Météo-France open data | actual global grid/lead and precipitation validation pending |
| Japan JMA GSM | JMA dissemination | raw access, licence and fields pending |
| China CMA GRAPES global | CMA dissemination | raw access, licence and current fields pending |
| Korea KIM global | KMA dissemination | current operational model and access pending |

Required products: pacc, p24, T2m, Z500 anomaly on actual global extents. Do not insert a fake catalogue entry or publish a regional image as global. Keep these models independent from the existing physical-model MM unless explicitly authorized. Validate accumulation window/reset/units, source terrain and covered DEM, then apply the existing elevation factor once before rendering/upload. Preserve raw physical fields, no invented values for missing data.

## Existing DEM path

Engine.make kind=win already calls the same precip_factor for all non-raw p24/pacc products of ECMWF 28/9km, GFS13/28km, ICON, UKMO and GEM. Regression checks all seven IDs and both products. Formula unchanged: chi=.27/km, ceiling 2500m, abs elevation difference capped 1.5km, factor clipped .5–2 before normalization, existing taper and neighborhood normalization. This is not proof of exact mass conservation or successful live products. No extra correction added; new global producer needs real terrain/DEM coverage and independent QC; do not extrapolate Iran DEM across globe. MM raw-then-correction migration remains pending.

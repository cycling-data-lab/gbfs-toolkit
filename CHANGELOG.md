# Changelog

All notable changes are documented here ([Keep a Changelog](https://keepachangelog.com),
[SemVer](https://semver.org)).

## [Unreleased]

### Added (research convenience helpers)
- **`stockout_episodes(panel)`** — contiguous empty/full outage *events* per station (start, end,
  duration, n_obs); the service-quality complement to `coverage_report` / `availability_stats`.
- **`turnover(panel, freq="1D")`** — per-station Σ|net_flow| activity proxy (a documented lower
  bound, by the aliasing argument).
- **`network_changes(old, new)`** — diff two station inventories: stations added / removed /
  recapacitated / moved (with distance), for longitudinal studies that span network growth.
- **`stations_near(points, info, radius_m)`** — accessibility primitive: per external POI, count
  of stations within a radius + nearest distance/id (the inverse of `features_within`, for equity).
- **`to_geojson(frame_or_gdf, path=...)`** — export stations/zones to GeoJSON for QGIS / kepler.gl.
- **`join_vehicle_types` / `join_pricing`** — resolve `vehicle_type_id` / `pricing_plan_id` onto a
  vehicles frame so "where are the e-bikes?" / cost joins are one call.

### Quality
- **Input-validation guards**: `join_availability`, `calculate_net_flow`, `coverage_report`,
  `detect_ghost_vehicles` and `link_transit_stops` now raise a clear `SchemaError` naming the
  missing columns instead of a cryptic `KeyError` deep in the call.
- **Test & coverage pass**: 99 → 115 tests, coverage 83% → 94%; added a CI coverage gate
  (`--cov-fail-under=85`). New coverage for the dynamic audit, `fetch_multiple` / module
  one-liners / feed delegators (offline), conditional GET, catalogue cache, the OSM geopandas
  path, panel resampling, manifests, and stats on empty/degenerate inputs.

### Added
- **Ghost-vehicle detection** (`fleet.detect_ghost_vehicles(vehicle_panel, idle_days=14,
  move_threshold_m=50)`): flags free-floating units advertised at the same spot for a long
  span (lost / broken / abandoned but still inflating availability), from a longitudinal
  vehicle panel. Returns per-vehicle `first_seen, last_seen, n_obs, observed_days,
  max_displacement_m, is_ghost`. Completes the dynamic fleet-health story alongside D1–D3.

## [0.8.0] — v1.0-readiness pass (provenance, robustness, methodology)

### Added
- **Provenance / citability** (`timeseries`): `coverage_report(panel, expected_freq)` quantifies
  per-station uptime and longest gap (missingness without imputation); `generate_manifest(lake_dir)`
  emits a SHA-256-per-partition manifest + dataset summary for Zenodo/Dataverse deposits.
- **Polite networking** (`fetch`): `build_session()` (pooled `requests.Session` with
  retry/backoff on 429/5xx — now the default in `fetch_multiple`); `fetch_feed_json(url, etag=...,
  last_modified=...)` does conditional GETs and raises `GBFSNotModified` on HTTP 304; structured
  logging under the `gbfs_toolkit` logger.
- **Exception hierarchy** (`errors`): `GBFSError` base with `GBFSFetchError`, `GBFSDiscoveryError`
  (also a `KeyError` for back-compat), `GBFSValidationError`, `GBFSNotModified`. `SchemaError` now
  subclasses `GBFSValidationError` (and still `ValueError`).
- **New canonical endpoints**: `to_canonical_system_regions` (region lookup) and
  `to_canonical_alerts` (`system_alerts` — disruptions that explain data anomalies), plus
  `GBFSFeed.system_regions()` / `.alerts()`.
- **Catalogue offline fallback**: `systems_catalog` caches successful downloads and falls back to
  the cached copy (with a warning) when the registry is unreachable.
- Documented methodology limits: the **aliasing / polling-Nyquist** caveat on `calculate_net_flow`
  (net flow is a lower bound on activity) and a prominent **edge-effect** warning on `ripley_k`.
- e2e round-trip test (raw → canonical → parquet → panel → net_flow + audit_frames + coverage) and
  CLI tests; coverage 83% → 87%.

### Changed
- Version `0.1.0` → `0.8.0`; development status Alpha → Beta.

## [Unreleased]

### Changed / Removed (pre-1.0 consolidation — second peer-review pass)
- **Decoupled analysis from fetching.** The join and audit logic are now pure functions on
  canonical frames — `join_availability(info, status)` and `audit_frames(info, status=...,
  ttl_seconds=..., system_id=...)` — so they work on frames read back from a Parquet lake, not
  only on a live `GBFSFeed`. `GBFSFeed.availability()` / `.audit()` are kept as thin
  delegators (no behaviour change for online use).
- The `availability()` `presence` column is now a **fixed-category `Categorical`**
  (`both` / `info_only` / `status_only`) instead of a free string.
- **Removed `osm.fetch_osm_around`** — fetching from OSM's rate-limited Overpass endpoint
  violated the no-HTTP / Bring-Your-Own-GeoDataFrame contract and was a CI/issue liability.
  Fetch with `osmnx` in your own script and pass the result to `enrich_with_osm`.
- **`calculate_net_flow` now reports the observed Δ only.** Removed `account_for_system`,
  `system_net_flow` and `is_rebalancing_suspected`: attributing a flow to rebalancing vs.
  organic demand is not identifiable from availability counts (even with system-wide mass
  conservation), so the library no longer ships a misleading cause label.

### Changed / Fixed (hardening — peer-review pass)
- **Nullable dtypes** in `to_canonical_station_status` (`Int64` counts, `boolean` flags) and
  `to_canonical_vehicles` — so the `availability()` **outer join** inserts `pd.NA` instead of
  silently upcasting integer counts and boolean flags to `float64` (which corrupted equality
  and boolean logic on orphaned stations).
- **A7 (null capacity) is now dockless-aware** — restricted to physical docked stations
  (excludes free-floating *and* virtual anchors, like A2/A6 already did). Mostly-dockless
  systems (Lime/Tier/Bird), whose capacity is null by design, no longer trip A7 spuriously.
- **A5 (bounding box) is antimeridian-safe** — longitudinal extent now uses the smallest
  covering arc, so a system straddling ±180° is no longer reported as Earth-spanning.
- `calculate_net_flow(account_for_system=True)` adds **mass-conservation** context: a
  `system_net_flow` column and a corroborated `is_rebalancing_suspected` that fires only when
  a station spike coincides with a same-sign system-wide change (fleet injection/removal).
  Internal van moves stay indistinguishable from organic demand at panel resolution (documented).
- `fetch_multiple(..., session=...)` accepts a shared `requests.Session` to pool connections
  across systems (avoids TCP/port exhaustion when polling many feeds on a schedule).

### Schema (future-proofing before 1.0)
- `STATION_STATUS_COLUMNS` gains **`is_installed`** (hardware deployed vs. `is_renting`).
- `VEHICLE_STATUS_COLUMNS` gains **`current_range_meters`** (e-bike/battery research) and
  **`pricing_plan_id`** (preserved, not parsed, for equity/pricing joins).

### Added
- **Descriptive stats** (`stats`): `system_profile` (one-glance numeric card of a snapshot —
  stations, capacity, occupancy, % empty/full/disabled/virtual, staleness), `compare_systems`
  (stacks profiles across cities into one table), `concentration_metrics` (capacity Gini +
  top-decile hub share — an equity lens kept *outside* the A1–A7 audit), and
  `availability_stats` (per-station longitudinal scalars: occupancy, time empty/full,
  volatility, diurnal amplitude, peak hour), and `coverage_stats` (station density,
  nearest-neighbour spacing, and the **Clark–Evans** dispersion index — density measured
  against the convex hull, or the real geofencing **service area** when zones are passed).
  Pure, pandas-only, strictly descriptive.
- **Standard spatial / inequality algorithms** (`stats`, numpy/scipy only, deterministic):
  `morans_i` (global Moran's I spatial autocorrelation + analytic z-score/p-value via
  k-NN weights), `ripley_k` (Ripley's K/L multi-scale clustering, density vs. hull or service
  area), `lorenz_curve` (inequality-curve points), and a **Theil index** added to
  `concentration_metrics`.
- **Per-vehicle-type station counts** (`to_canonical_station_vehicle_counts`): melts GBFS
  2.2+/3.x `vehicle_types_available` into a long frame (`STATION_VEHICLE_COUNTS_COLUMNS`), so
  "where are the e-bikes?" is a join — the aggregate `num_bikes_available` can't answer it.
- **Pricing-plan lookup** (`to_canonical_pricing_plans`): parses `system_pricing_plans.json`
  into `PRICING_PLAN_COLUMNS`, resolving the `pricing_plan_id` foreign key for cost/equity work.
- **`target_tz`** on `build_availability_panel` — converts `fetched_at`/`last_reported` to a
  local zone *before* dedup/resample, so daily aggregations cut at local midnight (UTC-midnight
  cuts silently corrupted diurnal analysis).
- **Parquet pushdown** in `build_availability_panel(columns=..., filters=...)` — project only
  the columns you need (join/dedup keys always read) and AND an extra `pyarrow.dataset`
  predicate with the built-in system/date filter, so multi-month / multi-city panels prune
  row-groups *before* materialising instead of OOM-ing.
- **Fleet reconciliation** (`fleet`): `reconcile_fleet_state(station_status, vehicles)` (and
  `GBFSFeed.reconcile_fleet()`) merge the docked aggregate counts and the per-vehicle feed
  into one labelled tally — `available_in_stations`, `free_floating_available/_reserved/
  _disabled`, `total_deployed`, `total_rentable`. Vehicles carrying a `station_id` are
  excluded from the deployed total (so the two feeds don't double-count) and the overlap is
  reported as `docked_in_vehicle_feed` / `double_count_avoided`. `VEHICLE_STATUS_COLUMNS`
  gains **`station_id`** (set when a vehicle is parked at a station, else NA → free-floating).
- **Geofencing / service areas** (`geofencing`, extra `[geo]`):
  `to_canonical_geofencing(raw, system_id=...)` parses `geofencing_zones.json` into a
  canonical `GeoDataFrame` (one row per zone, shapely geometry in EPSG:4326; v2.x
  `ride_allowed` and v3.x `ride_start/ride_end_allowed` reconciled; full per-vehicle-type
  `rules` preserved). `zones_for_points` is the point-in-zone spatial join (which zone each
  station/vehicle sits in), `zone_area_km2` reprojects to an equal-area CRS for metric,
  latitude-comparable density, and `GBFSFeed.geofencing_zones()` fetches them live. Unlocks
  sound spatial-density / equity analysis for free-floating & hybrid systems (the real
  service area, not a station convex hull). New `GEOFENCING_COLUMNS` contract.
- **Station surroundings / OSM** (`osm`, extra `[osm]`): `features_within(points, features,
  radius_m=300, category_col=...)` — the generic "what's nearby" primitive (counts within a
  radius + nearest distance + per-category `n_<cat>` breakdown, on `GeoKDTree`).
  `station_surroundings(info, transit=..., osm=..., radius_m=300)` — one-shot context frame
  combining transit feeders and OSM features. `enrich_with_osm` (reduces any GeoDataFrame
  geometry to representative points; Bring-Your-Own-GeoDataFrame) and the optional
  network-bound `fetch_osm_around` (osmnx). Routing/isochrones stay out of scope.
- **Multimodal** (`multimodal`): `link_transit_stops(info, gtfs_stops_df, radius_m=200)` —
  flags first/last-mile feeder docks near rail/bus by spatial proximity (GeoKDTree;
  Bring-Your-Own GTFS `stops`, no transit API, no schedules). Adds `nearest_stop_id`,
  `nearest_stop_dist_m`, `n_transit_within`, `is_transit_feeder`.
- **Station clustering** (`cluster`, extra `[cluster]`): `cluster_spatial`
  (HDBSCAN/DBSCAN on projected metres), `cluster_spectral` (geographic-affinity spectral
  clustering), and `cluster_diurnal_profiles` (occupancy-profile clustering → typologies).
  Modern options: automatic k by **silhouette** (`n_clusters="auto"`), shape clustering
  (`normalize="zscore"`), **soft GMM** (`method="gmm"`, with `cluster_confidence`),
  shape-aware **DTW** (`method="dtw"`, extra `[dtw]`/tslearn), and weekday/weekend split.
  Plus `diurnal_profiles` (reusable profile matrix) and `label_diurnal_typology`
  (human-readable station types: morning_origin / morning_destination / evening_origin /
  recreational / mostly_empty / mostly_full / stable).
- **Longitudinal data lake** (`timeseries`, extra `[parquet]`): `append_to_parquet`
  (Hive-partitioned by `system_id`/`date`, append-only, concurrent-safe),
  `build_availability_panel` (PyArrow partition-pruned read + dedup on
  `station_id`+`last_reported` + optional resample), `calculate_net_flow`
  (Δ bikes/station + `is_rebalancing_suspected`, NaN across unchanged `last_reported`).
- **`GeoKDTree`** (core `geo`): shared great-circle k-NN / radius index (scipy cKDTree
  over a 3-D unit sphere; EPSG:4326 contract). `find_nearest_stations` now uses it.
- **Fetch / scrape layer**: `GBFSFeed` (discover once, then `.station_information()`,
  `.station_status()`, `.vehicles()`, `.availability()`, `.audit()`, `.snapshot()`,
  `.summary()`); `parse_discovery`; one-liners `availability(url)` / `audit_feed(url)`;
  `fetch_multiple(system_ids)` (threaded, per-system error isolation). `get_json` is
  dependency-injectable for offline use.
- **Dynamic audit** `audit_dynamic` (D1 negative counts, D2 bikes+docks > capacity,
  D3 staleness) — the real-time counterpart to the static A1–A7 audit.
- **Derived metrics** `station_state` (empty/full/disabled/normal).
- **Geo helpers** `find_nearest_stations`, `haversine_m`, `to_gdf` (lazy geopandas, `[geo]`).
- **Catalogue** `filter_catalog(country_code=, city=, name=)` — find a system by place.

### Changed (canonical model — pre-1.0 schema hardening)
- StationInfo gains `is_virtual_station`.
- StationStatus gains `is_renting`, `is_returning`.
- VehicleStatus gains `vehicle_type_id` (pedal / e-bike / scooter).
- `last_reported` and `fetched_at` are now tz-aware **UTC** `datetime64[ns, UTC]`
  (previously unix ints) for unambiguous cross-city merges.

## [0.1.0] — 2026-06

Initial scaffold — consolidates GBFS tooling that was scattered across the lab's
research repositories into one tested, installable package.

### Added
- **Canonical data model** (`models`): version-independent `StationInfo`,
  `StationStatus`, `VehicleStatus`, `AuditVerdict` schemas + the A1–A7 rule
  definitions and thresholds.
- **Static semantic audit** (`audit.static.audit_static`): the A1–A7 taxonomy,
  ported from the published `gbfs-audit-catalogue` pipeline, operating on the
  canonical frame (no I/O).
- **Cross-version normalisation** (`normalize.to_canonical_station_info`): GBFS
  2.x string names and 3.x localized-array names; station-type inference.
- **Catalogue discovery** (`catalog.systems_catalog`, `catalog.resolve`): the
  MobilityData global `systems.csv`.
- **CLI**: `gbfs audit <station_information.json>` — the semantic counterpart to
  MobilityData's syntactic `gbfs-validator`.
- PEP 561 `py.typed`, CI (py3.10–3.13 + ruff + build), packaging, 14 unit tests.

### Notes
- Alpha: the public API may change before 1.0. Fetch/archive, the spatial and
  dynamic audits, and analysis panels are planned for 0.2–0.3.

[0.1.0]: https://github.com/cycling-data-lab/gbfs-toolkit/releases/tag/v0.1.0

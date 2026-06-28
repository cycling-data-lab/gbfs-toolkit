# Changelog

All notable changes are documented here ([Keep a Changelog](https://keepachangelog.com),
[SemVer](https://semver.org)).

## [1.6.0] - feed governance, service stress, panel ergonomics

### Added
Four descriptive metrics (grounded in the bike-share literature and an external review)
and a set of everyday panel utilities. All within the descriptive scope (no
origin-destination, routing, prediction or imputation).

- **Feed governance.** `vehicle_id_persistence` characterises whether a feed rotates or
  keeps its `vehicle_id` (the GBFS 2.1+ privacy guidance), via the rolling Jaccard overlap
  of the live id-set and the observed id lifespan. The inverse of this persistence is the
  ceiling on origin-destination identifiability, so it is the check that tells a study
  whether trip-level work is even admissible (a feed property, not trip inference).
- **Service stress.** `boundary_stress` reports the share of time a station sits *near*
  empty or full (absolute thresholds, default `<= 2`), the perceived-unreliability that the
  strict `station_outage_rates` (`== 0`) undercounts; drop-off stress is `NA` for
  free-floating / zero-capacity stations.
- **Spatial redundancy.** `spatial_outage_redundancy` separates a station's local
  stockouts from *systemic* failures where every station within a walking radius is also
  empty, the rupture a user cannot walk around (uses the existing `GeoKDTree`).
- **System-level coverage.** `coverage_report(level="system")` summarises a feed's temporal
  completeness for a paper's data section: window, median cadence, cadence jitter and
  overall station-hours yield (the per-station report is unchanged, `level="station"`).
- **Panel ergonomics.** `add_local_time` (tz conversion that handles the index),
  `resample_panel` (dtype-safe step-function resampling onto a fixed grid),
  `insert_explicit_gaps` (mark collection outages with `NaN` rows so plots break honestly),
  `extract_snapshot_asof` (the city's state at one instant), `to_wide_matrix` (long to
  station-by-time matrix) and `filter_by_bbox` (the missing rectangular spatial filter).

## [1.5.0] - feed-first audit, research algorithms, generated reference

### Added
Audit goes feed-first and batch, and the descriptive analysis surface gains the
algorithms a quantitative study reports. All within the descriptive scope (no
origin-destination, routing, prediction or imputation).

- **Audit pipeline.** `audit_static` now exposes every policy threshold
  (`a5_area_km2`, `a6_tau`, `a7_tau`, `n_min`; `a4_sigma` already public), defaults
  unchanged. `audit_sensitivity` (threshold-robustness sweep with the Jaccard
  overlap of the flagged set) and `flag_rate_ci` (seeded cluster-bootstrap intervals
  on flag rates) make robustness and uncertainty reproducible from one call.
- **Feed-intrinsic classification.** `classify_from_vehicle_types` (A1 car-sharing
  from the GBFS v3 `form_factor`), `classify_from_virtual_station` (free-floating
  from `is_virtual_station`), `overcapacity_ratio` + `reclassify_overcapacity` (the
  A3 conditional-averaging signature), `capacity_convention` (the six capacity
  semantics) and `flag_sentinel_coordinates` (the (0,0) null-island filter).
- **Batch audit.** `audit_catalogue` fetches and audits many systems in one call,
  returning the per-station verdict and a per-system status.
- **Research algorithms.** `fdr_adjust` and `local_morans_i(fdr=True)`
  (Benjamini-Hochberg control for LISA), `theil_index` (between/within decomposable)
  and `palma_ratio` (equity), `two_step_fca` exponential (gravity) decay (E2SFCA),
  `rebalancing_tension` (minimum-work spatial fragmentation via the Wasserstein
  earth-mover distance), `block_bootstrap_ci` + `effective_sample_size` (honest
  uncertainty for autocorrelated series), and `censored_time_ratio` (observability
  loss at saturation).
- **Human-validation helpers.** `krippendorff_alpha`, `cohen_kappa`,
  `wilson_interval` for construct-validity studies.

### Fixed
- `resolve` preferred the operator website `url` over the GBFS auto-discovery
  endpoint (fetched the homepage instead of `gbfs.json`).
- `gini` could return a tiny negative on all-equal inputs (float roundoff).

### Documentation
- The API reference is now a generated per-function catalogue (one page per object
  from `__all__`, a thematic landing) with clickable pandas/numpy/scipy types and a
  source button; versioned with `mike`. Doctested `Examples` on the analytical
  surface (run in CI), a docstring-coverage gate (`interrogate`), and a ten-page
  How-To scenario set (audit, collection, history, equity, rigour, free-floating &
  ghost fleets, reliability, context, macro-scale).

## [1.4.0] - advanced descriptive analytics

### Added
Five research-grade descriptive functions, all on the `.gbfs` accessor and within the descriptive
scope (no origin-destination, routing, prediction or imputation). Closes #2.

- `local_morans_i` (LISA): per-station spatial-autocorrelation hotspots and cold spots with
  conditional-permutation pseudo p-values and HH/LL/HL/LH cluster labels, where the global
  `morans_i` only gives one number. `[geo]`/scipy. Anselin (1995).
- `availability_synchrony`: pairwise correlation of station availability series over their common
  support, returned as an upper-triangle edge list for downstream network analysis (bring your own
  graph). Correlates observed availability only, never trips. O'Brien et al. (2014).
- `diurnal_bimodality`: Sarle's bimodality coefficient of each station's diurnal profile, a
  continuous scalar separating commuter (bimodal) from recreational (unimodal) stations.
- `outage_survival`: empirical survival function and median / P90 time-to-recovery of stockout
  episodes, with the right-censoring caveat stated and never imputed. Kaplan-Meier (1958).
- `temporal_concentration`: per-station Gini of activity across time-of-day bins (temporal peaking),
  the temporal analogue of `dynamic_gini_index`.

## [1.3.0] - descriptive research indicators

### Added
Seventeen pure, descriptive indicators that turn the panel into publication-ready summary
statistics. All are strictly descriptive (no origin-destination, routing, prediction or
imputation), operate on the canonical frames, and are exposed on the `.gbfs` accessor.

- **Service and equity**: `service_reliability_index` (level-of-service probability per station
  and time-of-day), `station_outage_rates` (stockout and saturation fractions),
  `capacity_utilization` (bikes over capacity, nullable), `dynamic_gini_index` (Gini of available
  bikes over time), `two_step_fca` (two-step floating catchment area accessibility, `[geo]`).
- **Observed dynamics**: `flow_asymmetry_ratio` (inflow over outflow), `fleet_turnover_proxy`
  (a lower-bound usage rate per vehicle), `cumulative_imbalance` (drift), `docking_pressure`
  (typical inflow over free docks), `spatial_center_of_mass` (fleet centre of gravity over time),
  `spatial_entropy` (Shannon entropy of the free-floating distribution).
- **Temporal and sampling**: `temporal_autocorrelation` (ACF at hour/day/week lags),
  `aliasing_vulnerability` (a Nyquist-limit diagnostic), `diurnal_summary_stats` (hour-of-day
  mean/median/P5/P95), `temporal_context_features` (is_weekend, time_block, optional is_holiday).
- **Fleet and exogenous**: `vehicle_idle_time` (zombie-fleet share over time),
  `join_exogenous_timeseries` (safe `merge_asof` of weather/traffic onto the panel, bring your own).

## [1.2.0] - reproduce the audit catalogue from the library

### Added
- `audit_static` gains two keyword options so the published `gbfs-audit-catalogue` verdicts
  can be reproduced exactly from the library:
  - **`a7_scope="docked"` (default) or `"all"`**. The default keeps A7 dockless-aware (the
    toolkit's behaviour since 1.0). `"all"` evaluates the null-capacity rate over every
    station, reproducing the catalogue's original A7, under which a fully free-floating system
    with null capacities is flagged.
  - **`a4_sigma=3.0` (default)**. Exposes the A4 nearest-neighbour outlier multiplier for
    sensitivity analysis, so a threshold sweep no longer needs to monkey-patch a module constant.
- Verified byte-identical against the 46 307-station catalogue: with `a7_scope="all"`, all of
  A1 to A7 match the published flags, and `a4_sigma` reproduces the published 2.0 to 4.0 sweep.
- **CLI rendering adapts to context.** `gbfs audit` prints a coloured table when `rich` is
  installed and the output is an interactive terminal, plain text otherwise. New flags:
  `--json` (machine-readable output for pipelines), `--a7-scope {docked,all}`, and `--no-color`.
  `rich` lives behind the new optional `[cli]` extra; the core install is unchanged.
- **`fetch_multiple(progress=True)`** reports progress on a long multi-system pull: a tqdm bar
  when tqdm is installed (also in `[cli]`), otherwise periodic log lines. Feeds are now consumed
  as they complete, and a per-system failure is logged as well as recorded.
- **Doctests** on `occupancy` and `station_state`, run in CI, so the reference examples cannot
  drift from the code.

## [1.1.0] - conformance & robustness (from real-world migration)

### Added
- `detect_frozen_stations` gains **`strict=True`** (a column counts as frozen only if it never
  changes across the whole observed window, not merely a long run) and **`columns=(...)`**
  (require *all* listed columns frozen, e.g. bikes *and* docks). Motivated by cross-validating
  the `gbfs-dynamic-audit` zombie detector against the toolkit.
- Vehicle schema gains **`current_fuel_percent`** (GBFS 3.0 battery fraction).

### Fixed / Changed
- **Language-nested feeds** (old GBFS 1.x/2.x `data.<lang>.<key>`) are now tolerated by every
  normalizer (`to_canonical_station_info` / `_status` / `_vehicles` / `_vehicle_types` /
  `_pricing_plans` / `_system_regions` / `_alerts`), not just discovery. Surfaced by migrating
  bikeshare-data-explorer, whose collectors kept hand-rolled flattening for this reason.
- `to_canonical_station_status` also reads GBFS 3.0 **`vehicle_docks_available`** as a fallback
  for `num_docks_available` (companion to the 1.0.1 `num_vehicles_available` fix).
- CI now runs the `load_example` **doctest**.

## [1.0.1]

### Fixed
- `to_canonical_station_status` now reads the GBFS 3.0 **`num_vehicles_available`** field as a
  fallback for `num_bikes_available` (3.0 renamed it). Surfaced while migrating a real consumer
  (bikeshare-data-explorer) onto the toolkit.

## [1.0.0] - first stable release

Promotes `1.0.0rc1` unchanged (validated by a clean install from PyPI and the full test suite).
The canonical schema and public API are now stable under SemVer. Development status →
Production/Stable.

## [1.0.0rc1] - first public release candidate

Frozen canonical schema and public API after three peer-review passes. Adds `METHODOLOGY.md`
(audit thresholds, the polling/aliasing limit, spatial-stat caveats), `CONTRIBUTING.md`, and a
PyPI Trusted-Publishing release workflow. The sections below list everything since 0.1.0.

### Added (library-API conventions)
- **`.gbfs` pandas accessor**: fluent chaining over the pure functions: `df.gbfs.audit()`,
  `av.gbfs.occupancy()`, `panel.gbfs.net_flow()`, `info.gbfs.join_status(status)`. Single-frame
  ops map directly; two-frame ops take the second frame as the argument.
- **`load_example()`**: a small, deterministic bundled GBFS snapshot (central Paris) for docs,
  doctests and offline tests; returns canonical `(station_info, station_status)`.
- **`show_versions()`**: environment/dependency diagnostic for bug reports.
- **`validate_schema(df, schema)` / `coerce_schema(df, schema)`**: public schema check/cast over
  the canonical contracts (`SCHEMAS` registry); assert or repair a mutated frame before writing it.
- **`GBFSFeed.__repr__` / `_repr_html_`**: readable repr in shells/Jupyter (cached state only,
  never triggers a network call).

### Added (distilled from the lab's research code)
- **`detect_frozen_stations(panel)`**: flags a value stuck unchanged over an active window
  while the feed stays fresh (dead sensor), distinct from staleness (D3) and stockouts. Seen
  reimplemented across three dynamic-audit repos.
- **`flow_balance(panel)`**: per-station inflow/outflow split + source↔sink balance ratio
  (the "Keq" several notebooks computed by hand).
- **`turnover(..., normalize="capacity")`**: capacity-normalised activity, comparable across
  station sizes.
- **`normalize_operator(name)`**: canonical operator brand from a system id/name
  (`smovengo` → `Vélib' Métropole`); non-lossy. Lifted from the audit-catalogue's `detect_operator`.
- **`cyclical_time_features(timestamps)`**: sin/cos calendar encoding (the single most
  duplicated helper across the lab's repos).

### Added (ergonomic one-liners)
- **`drop_flagged(stations)`**: audit and keep the clean subset in one call.
- **`occupancy(availability)`**: the bikes/(bikes+docks) ratio, vectorised, NaN-safe on the
  empty-and-no-docks case (everyone was recomputing it inconsistently).
- **`filter_vehicles(vehicles, types, form_factor=…, propulsion=…)`** and **`ebikes(...)`**:
  resolve vehicle types and filter in one call ("where are the e-bikes?").
- **In-process catalogue cache**: `systems_catalog` now memoises the parsed registry for the
  process (with `refresh=True` to force), so resolving many systems in a loop downloads once.

### Added (research convenience helpers)
- **`stockout_episodes(panel)`**: contiguous empty/full outage *events* per station (start, end,
  duration, n_obs); the service-quality complement to `coverage_report` / `availability_stats`.
- **`turnover(panel, freq="1D")`**: per-station Σ|net_flow| activity proxy (a documented lower
  bound, by the aliasing argument).
- **`network_changes(old, new)`**: diff two station inventories: stations added / removed /
  recapacitated / moved (with distance), for longitudinal studies that span network growth.
- **`stations_near(points, info, radius_m)`**: accessibility primitive: per external POI, count
  of stations within a radius + nearest distance/id (the inverse of `features_within`, for equity).
- **`to_geojson(frame_or_gdf, path=...)`**: export stations/zones to GeoJSON for QGIS / kepler.gl.
- **`join_vehicle_types` / `join_pricing`**: resolve `vehicle_type_id` / `pricing_plan_id` onto a
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

## [0.8.0] - v1.0-readiness pass (provenance, robustness, methodology)

### Added
- **Provenance / citability** (`timeseries`): `coverage_report(panel, expected_freq)` quantifies
  per-station uptime and longest gap (missingness without imputation); `generate_manifest(lake_dir)`
  emits a SHA-256-per-partition manifest + dataset summary for Zenodo/Dataverse deposits.
- **Polite networking** (`fetch`): `build_session()` (pooled `requests.Session` with
  retry/backoff on 429/5xx, now the default in `fetch_multiple`); `fetch_feed_json(url, etag=...,
  last_modified=...)` does conditional GETs and raises `GBFSNotModified` on HTTP 304; structured
  logging under the `gbfs_toolkit` logger.
- **Exception hierarchy** (`errors`): `GBFSError` base with `GBFSFetchError`, `GBFSDiscoveryError`
  (also a `KeyError` for back-compat), `GBFSValidationError`, `GBFSNotModified`. `SchemaError` now
  subclasses `GBFSValidationError` (and still `ValueError`).
- **New canonical endpoints**: `to_canonical_system_regions` (region lookup) and
  `to_canonical_alerts` (`system_alerts`: disruptions that explain data anomalies), plus
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

### Changed / Removed (pre-1.0 consolidation, second peer-review pass)
- **Decoupled analysis from fetching.** The join and audit logic are now pure functions on
  canonical frames: `join_availability(info, status)` and `audit_frames(info, status=...,
  ttl_seconds=..., system_id=...)`, so they work on frames read back from a Parquet lake, not
  only on a live `GBFSFeed`. `GBFSFeed.availability()` / `.audit()` are kept as thin
  delegators (no behaviour change for online use).
- The `availability()` `presence` column is now a **fixed-category `Categorical`**
  (`both` / `info_only` / `status_only`) instead of a free string.
- **Removed `osm.fetch_osm_around`**: fetching from OSM's rate-limited Overpass endpoint
  violated the no-HTTP / Bring-Your-Own-GeoDataFrame contract and was a CI/issue liability.
  Fetch with `osmnx` in your own script and pass the result to `enrich_with_osm`.
- **`calculate_net_flow` now reports the observed Δ only.** Removed `account_for_system`,
  `system_net_flow` and `is_rebalancing_suspected`: attributing a flow to rebalancing vs.
  organic demand is not identifiable from availability counts (even with system-wide mass
  conservation), so the library no longer ships a misleading cause label.

### Changed / Fixed (hardening, peer-review pass)
- **Nullable dtypes** in `to_canonical_station_status` (`Int64` counts, `boolean` flags) and
  `to_canonical_vehicles`, so the `availability()` **outer join** inserts `pd.NA` instead of
  silently upcasting integer counts and boolean flags to `float64` (which corrupted equality
  and boolean logic on orphaned stations).
- **A7 (null capacity) is now dockless-aware**: restricted to physical docked stations
  (excludes free-floating *and* virtual anchors, like A2/A6 already did). Mostly-dockless
  systems (Lime/Tier/Bird), whose capacity is null by design, no longer trip A7 spuriously.
- **A5 (bounding box) is antimeridian-safe**: longitudinal extent now uses the smallest
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
- **Descriptive stats** (`stats`): `system_profile` (one-glance numeric card of a snapshot:
  stations, capacity, occupancy, % empty/full/disabled/virtual, staleness), `compare_systems`
  (stacks profiles across cities into one table), `concentration_metrics` (capacity Gini +
  top-decile hub share, an equity lens kept *outside* the A1–A7 audit), and
  `availability_stats` (per-station longitudinal scalars: occupancy, time empty/full,
  volatility, diurnal amplitude, peak hour), and `coverage_stats` (station density,
  nearest-neighbour spacing, and the **Clark–Evans** dispersion index: density measured
  against the convex hull, or the real geofencing **service area** when zones are passed).
  Pure, pandas-only, strictly descriptive.
- **Standard spatial / inequality algorithms** (`stats`, numpy/scipy only, deterministic):
  `morans_i` (global Moran's I spatial autocorrelation + analytic z-score/p-value via
  k-NN weights), `ripley_k` (Ripley's K/L multi-scale clustering, density vs. hull or service
  area), `lorenz_curve` (inequality-curve points), and a **Theil index** added to
  `concentration_metrics`.
- **Per-vehicle-type station counts** (`to_canonical_station_vehicle_counts`): melts GBFS
  2.2+/3.x `vehicle_types_available` into a long frame (`STATION_VEHICLE_COUNTS_COLUMNS`), so
  "where are the e-bikes?" is a join: the aggregate `num_bikes_available` can't answer it.
- **Pricing-plan lookup** (`to_canonical_pricing_plans`): parses `system_pricing_plans.json`
  into `PRICING_PLAN_COLUMNS`, resolving the `pricing_plan_id` foreign key for cost/equity work.
- **`target_tz`** on `build_availability_panel`: converts `fetched_at`/`last_reported` to a
  local zone *before* dedup/resample, so daily aggregations cut at local midnight (UTC-midnight
  cuts silently corrupted diurnal analysis).
- **Parquet pushdown** in `build_availability_panel(columns=..., filters=...)`: project only
  the columns you need (join/dedup keys always read) and AND an extra `pyarrow.dataset`
  predicate with the built-in system/date filter, so multi-month / multi-city panels prune
  row-groups *before* materialising instead of OOM-ing.
- **Fleet reconciliation** (`fleet`): `reconcile_fleet_state(station_status, vehicles)` (and
  `GBFSFeed.reconcile_fleet()`) merge the docked aggregate counts and the per-vehicle feed
  into one labelled tally: `available_in_stations`, `free_floating_available/_reserved/
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
  radius_m=300, category_col=...)`: the generic "what's nearby" primitive (counts within a
  radius + nearest distance + per-category `n_<cat>` breakdown, on `GeoKDTree`).
  `station_surroundings(info, transit=..., osm=..., radius_m=300)`: one-shot context frame
  combining transit feeders and OSM features. `enrich_with_osm` (reduces any GeoDataFrame
  geometry to representative points; Bring-Your-Own-GeoDataFrame) and the optional
  network-bound `fetch_osm_around` (osmnx). Routing/isochrones stay out of scope.
- **Multimodal** (`multimodal`): `link_transit_stops(info, gtfs_stops_df, radius_m=200)`:
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
  D3 staleness): the real-time counterpart to the static A1–A7 audit.
- **Derived metrics** `station_state` (empty/full/disabled/normal).
- **Geo helpers** `find_nearest_stations`, `haversine_m`, `to_gdf` (lazy geopandas, `[geo]`).
- **Catalogue** `filter_catalog(country_code=, city=, name=)`: find a system by place.

### Changed (canonical model, pre-1.0 schema hardening)
- StationInfo gains `is_virtual_station`.
- StationStatus gains `is_renting`, `is_returning`.
- VehicleStatus gains `vehicle_type_id` (pedal / e-bike / scooter).
- `last_reported` and `fetched_at` are now tz-aware **UTC** `datetime64[ns, UTC]`
  (previously unix ints) for unambiguous cross-city merges.

## [0.1.0] - 2026-06

Initial scaffold, consolidates GBFS tooling that was scattered across the lab's
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
- **CLI**: `gbfs audit <station_information.json>`: the semantic counterpart to
  MobilityData's syntactic `gbfs-validator`.
- PEP 561 `py.typed`, CI (py3.10–3.13 + ruff + build), packaging, 14 unit tests.

### Notes
- Alpha: the public API may change before 1.0. Fetch/archive, the spatial and
  dynamic audits, and analysis panels are planned for 0.2–0.3.

[0.1.0]: https://github.com/cycling-data-lab/gbfs-toolkit/releases/tag/v0.1.0

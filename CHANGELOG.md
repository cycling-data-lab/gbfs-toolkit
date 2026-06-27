# Changelog

All notable changes are documented here ([Keep a Changelog](https://keepachangelog.com),
[SemVer](https://semver.org)).

## [Unreleased]

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

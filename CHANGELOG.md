# Changelog

All notable changes are documented here ([Keep a Changelog](https://keepachangelog.com),
[SemVer](https://semver.org)).

## [Unreleased]

### Added
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

# gbfs-toolkit

[![CI](https://github.com/cycling-data-lab/gbfs-toolkit/actions/workflows/ci.yml/badge.svg)](https://github.com/cycling-data-lab/gbfs-toolkit/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/cycling-data-lab/gbfs-toolkit/blob/main/LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)

**Research-grade ingestion and *semantic* quality audit for GBFS bike-share feeds.**

MobilityData's [`gbfs-validator`](https://github.com/MobilityData/gbfs-validator) checks
that a feed is *syntactically* valid. `gbfs-toolkit` checks whether it is *semantically*
trustworthy and analysis-ready. It implements the **A1–A7 quality taxonomy** of Fossé & Pallares
([`gbfs-audit-catalogue`](https://github.com/cycling-data-lab/gbfs-audit-catalogue)) and
normalises feeds into a **stable, version-independent data model** that can be reused across
studies.

## Why

Every bike-share study re-implements the same plumbing: discover feeds, normalise GBFS
1.x/2.x/3.x, and, in the more difficult case, cope with the semantic defects that the syntactic validator
cannot see, such as placeholder capacities, phantom docks, transposed coordinates, and out-of-perimeter
stations. This package consolidates that work into one tested interface, so the audit is a verdict
per station rather than a re-run of someone's notebook.

## Install

```bash
pip install gbfs-toolkit            # from PyPI (when released)
pip install -e ".[dev]"            # from a local clone
```

Core depends only on numpy / scipy / pandas. Network discovery/fetch uses the optional
`[fetch]` extra (`requests`).

## Quick start

```python
import gbfs_toolkit as gb

info, status = gb.load_example()          # bundled sample, no network needed
av = info.gbfs.join_status(status)        # fluent .gbfs accessor (or gb.join_availability)
clean = info.gbfs.drop_flagged()          # audit A1–A7 and keep the trustworthy stations
av.gbfs.occupancy()                       # bikes / (bikes + docks), NaN-safe
```

From your own feed:

```python
import json

raw = json.load(open("station_information.json"))
stations = gb.to_canonical_station_info(raw, system_id="velib")   # version-independent frame
verdict  = gb.audit_static(stations)                              # A1–A7 per station
clean    = stations[~verdict["flagged"].to_numpy()]              # quality filter in one line
```

Every function is also a `.gbfs` accessor method, and pure (so `df.pipe(gb.occupancy)` works).
`gb.show_versions()` prints an environment report for bug reports.

Command line (the semantic counterpart to `gbfs-validator`):

```bash
gbfs audit station_information.json --system-id velib --out verdict.csv
```

## The A1–A7 semantic taxonomy

| Flag | Rule | Signature | Level |
|---|---|---|---|
| A1 | Out-of-domain inclusion | car-sharing advertised as bike-sharing | station |
| A2 | Placeholder capacity | constant non-zero capacity across a whole system | system |
| A3 | Structural over-capacity | free-floating fleet anchors | station |
| A4 | Geospatial error | transposed coords / stations far from neighbours (3σ) | station |
| A5 | Out-of-perimeter | system bounding box > 50,000 km² | system |
| A6 | Zero-capacity dock | ≥1% of docked stations declare capacity = 0 | system |
| A7 | Null capacity field | ≥50% of stations declare capacity = NaN | system |

Thresholds match the published catalogue, so verdicts reproduce.

## Canonical data model (the stable contract)

Ingestion is normalised **once** into version-independent frames. Audit and analysis then
operate purely on these. Downstream code depends on these column names, never on raw GBFS
JSON.

- **StationInfo**: `system_id, station_id, name, lat, lon, capacity, station_type, is_virtual_station`
- **StationStatus**: `system_id, station_id, num_bikes_available, num_docks_available, is_renting, is_returning, last_reported, fetched_at, gbfs_version`
- **VehicleStatus**: `system_id, vehicle_id, vehicle_type_id, lat, lon, is_reserved, is_disabled, fetched_at, gbfs_version`
- **AuditVerdict**: `system_id, station_id, A1…A7, flagged, reason`

`last_reported` and `fetched_at` are tz-aware **UTC** timestamps (`datetime64[ns, UTC]`) so
feeds from different cities merge unambiguously.

## Daily ergonomics

```python
import gbfs_toolkit as gb

# discover by city (you rarely know the system_id)
cat   = gb.systems_catalog()
paris = gb.filter_catalog(cat, country_code="FR", city="Paris")

feed  = gb.GBFSFeed.from_url(url)
feed.summary()                       # one-glance card: stations, bikes, staleness, version
avail = feed.availability()          # bikes/docks + name/coords/capacity, one frame
avail["state"] = gb.station_state(avail)          # empty / full / disabled / normal
problems = gb.audit_dynamic(avail)                # negative counts, over-capacity, stale
near  = gb.find_nearest_stations(48.85, 2.35, feed.station_information(), k=3)

# many systems at once (threaded), broken feeds isolated as Exceptions
feeds = gb.fetch_multiple(["velib", "bixi", "lyon"], max_workers=5)
```

## Longitudinal data lake

Turn a stream of snapshots into an analysis-ready panel. The library owns the
formatting / dedup / I/O; your orchestrator (cron, Airflow, and similar) owns the polling loop.
Requires the optional `[parquet]` extra (`pyarrow`).

```python
import gbfs_toolkit as gb

# in your poller (every N minutes):
gb.append_to_parquet(feed.station_status(), "lake/")   # Hive-partitioned by system_id/date

# in your analysis:
panel = gb.build_availability_panel("lake/", system_id="velib",
                                    start_time="2026-06-01", resample_freq="5min")
flow  = gb.calculate_net_flow(panel)   # Δ bikes/station per poll (observed flow only)
```

`build_availability_panel` filters partitions *before* loading (memory-bounded),
de-duplicates redundant polls (same `station_id` + `last_reported`), and optionally
resamples each station to a fixed cadence.

## Station clustering (`[cluster]`)

Three lenses on "which stations belong together": spatial, topological, and behavioural.

```python
gb.cluster_spatial(info, method="hdbscan")          # density zones (projected metres)
gb.cluster_spectral(info, k=6)                       # network/topology groups
gb.cluster_diurnal_profiles(panel, n_clusters=4)    # daily-rhythm typologies
```

`cluster_diurnal_profiles` turns the longitudinal panel into station **typologies**,
for example "morning commuter origin" (full at night, empty by day) versus "recreational", from each
station's 24-hour occupancy profile (robust to irregular sampling). Available options include
auto-`k` by silhouette, shape clustering (`normalize="zscore"`), soft GMM, DTW
(`method="dtw"`, extra `[dtw]`), and weekday/weekend split. `label_diurnal_typology`
turns clusters into **named** types. This analysis is a primary use of the data lake.

## Multimodal: bikeshare ↔ transit

```python
stops = pd.read_csv("gtfs/stops.txt")               # bring your own GTFS stops
linked = gb.link_transit_stops(info, stops, radius_m=200)
feeders = linked[linked["is_transit_feeder"]]       # first/last-mile docks near rail/bus
```

Pure spatial proximity on `GeoKDTree` (no transit API, no schedules): `is_transit_feeder`,
`nearest_stop_dist_m`, `n_transit_within`.

## Station surroundings: what is around each dock (`[osm]`)

```python
# generic "what's nearby", works for any point dataset (POIs, shops, …)
gb.features_within(info, pois, radius_m=300, category_col="amenity")  # n_within, n_cafe, …

# bring your own OSM frame (fetch it yourself, e.g. osmnx.features_from_point)
# one-shot context: transit feeders + OSM features, in one frame
ctx = gb.station_surroundings(info, transit=stops, osm=osm_gdf, radius_m=300)
```

The radius summarisation (counts, per-category breakdown, and nearest distance) is the durable,
tested core. Data acquisition follows a **Bring Your Own GeoDataFrame** model, so the library never depends
on a live Overpass endpoint. Routing and isochrones stay out of scope (use OSMnx / pandana).

## Descriptive stats: the bikeshare `describe()`

```python
gb.system_profile(av)                       # stations, capacity, occupancy, % empty/full/…
gb.compare_systems({"velib": av1, "bixi": av2})   # one comparison row per city
gb.concentration_metrics(info)              # capacity Gini + top-decile hub share (equity)
gb.coverage_stats(info, zones=zones)        # density, nearest-neighbour, Clark–Evans dispersion
gb.availability_stats(panel)                # per-station: occupancy, peak hour, volatility
```

Standard spatial / inequality algorithms (numpy/scipy only, deterministic):

```python
gb.morans_i(info, "occupancy")              # spatial autocorrelation (+ z-score / p-value)
gb.ripley_k(info, radii=[100, 250, 500])    # multi-scale clustering: L>0 clustered, <0 dispersed
gb.lorenz_curve(info)                       # inequality curve to plot (Gini/Theil in concentration_metrics)
```

These produce readable, comparable summaries that are strictly descriptive (no OD/trip inference). `system_profile`
is a one-glance numeric card of a snapshot. `concentration_metrics` is an equity lens (kept
*outside* the published A1–A7 audit, since it is a metric and not a quality verdict).
`availability_stats` turns a longitudinal panel into per-station scalars (pass a `target_tz`
panel for local-time peaks).

## Fleet reconciliation: where the bikes actually are

```python
tally = gb.reconcile_fleet_state(status, vehicles)   # or feed.reconcile_fleet()
tally["total_deployed"]        # on the street: stations + free-floating, overlap excluded
tally["total_rentable"]        # available in stations + available free-floating
tally["double_count_avoided"]  # vehicles a naive sum would have counted twice
```

GBFS reports the same fleet twice: aggregate docked counts in `station_status` and
individual units (some parked at stations) in `vehicle_status`. Naively adding them
double-counts every vehicle sitting at a dock. The reconciler excludes station-parked
vehicles from the deployed total and surfaces the overlap instead of hiding it.

## Geofencing / service areas (`[geo]`)

```python
zones = gb.to_canonical_geofencing(raw, system_id="lime")  # GeoDataFrame of operator polygons
tagged = gb.zones_for_points(info, zones)                   # which zone each station sits in
density = len(info) / gb.zone_area_km2(zones).sum()         # bikes per km² of *real* service area
no_park = tagged[tagged["station_parking"] == False]        # stations in park-restricted zones
```

For free-floating / hybrid systems the real footprint is the operator's polygons, not a
convex hull of stations. `to_canonical_geofencing` parses `geofencing_zones.json` (v2.x
`ride_allowed` and v3.x `ride_start/ride_end_allowed` reconciled), `zones_for_points` is the
point-in-zone spatial join, and `zone_area_km2` reprojects to an equal-area CRS so density is
metric and latitude-comparable. The full per-vehicle-type `rules` list is preserved.

## Polite scraping & provenance (research-grade)

```python
session = gb.build_session()                 # pooled, retry/backoff on 429/5xx (default in fetch_multiple)
resp = gb.fetch_feed_json(url, etag=prev_etag)   # conditional GET; raises GBFSNotModified on HTTP 304
...
gb.coverage_report(panel, expected_freq="5min")  # per-station uptime / longest gap (no imputation)
gb.generate_manifest("lake/")                # SHA-256 per partition + summary → cite on Zenodo
```

Built for scrapers that run for months: retries/backoff, conditional GETs (skip unchanged
snapshots), an offline catalogue cache, a `GBFSError` exception hierarchy, and provenance tools
so a dataset is **citable and verifiable**. Missing data stays missing: `coverage_report`
quantifies it rather than imputing.

## Examples

Runnable, end-to-end scripts live in [`examples/`](https://github.com/cycling-data-lab/gbfs-toolkit/tree/main/examples): auditing an unknown feed,
cron-driven collection into a Parquet lake, longitudinal analysis (coverage, typologies,
turnover), and a network equity/coverage report.

## Project status

The package is stable at 1.1.0 and follows semantic versioning. The canonical schema and
the public API are frozen, so studies built on the data model and function signatures remain
reproducible across releases. See the Changelog for the full release history.

## Methodology & limitations

[`METHODOLOGY.md`](https://github.com/cycling-data-lab/gbfs-toolkit/blob/main/METHODOLOGY.md) documents the A1–A7 thresholds, the dynamic checks, the
polling/aliasing limit on flows, and what the spatial statistics can and cannot claim. Read it
before building a study on the toolkit.

## How to cite

See [`CITATION.cff`](https://github.com/cycling-data-lab/gbfs-toolkit/blob/main/CITATION.cff). The semantic taxonomy is from the
`gbfs-audit-catalogue` dataset paper (Fossé & Pallares, 2026).

## License

[MIT](https://github.com/cycling-data-lab/gbfs-toolkit/blob/main/LICENSE). Affiliated with [CESI LINEACT (EA 7527)](https://lineact.cesi.fr), Montpellier, France.

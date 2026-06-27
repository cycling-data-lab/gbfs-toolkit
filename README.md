# gbfs-toolkit

[![CI](https://github.com/cycling-data-lab/gbfs-toolkit/actions/workflows/ci.yml/badge.svg)](https://github.com/cycling-data-lab/gbfs-toolkit/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)

**Research-grade ingestion and *semantic* quality audit for GBFS bike-share feeds.**

MobilityData's [`gbfs-validator`](https://github.com/MobilityData/gbfs-validator) checks
that a feed is *syntactically* valid. `gbfs-toolkit` checks whether it is *semantically*
trustworthy and analysis-ready — the **A1–A7 quality taxonomy** of Fossé & Pallares
([`gbfs-audit-catalogue`](https://github.com/cycling-data-lab/gbfs-audit-catalogue)) — and
normalises feeds into a **stable, version-independent data model** you can reuse across
studies.

## Why

Every bike-share study re-implements the same plumbing — discover feeds, normalise GBFS
1.x/2.x/3.x, and (the hard part) cope with the semantic defects the syntactic validator
cannot see: placeholder capacities, phantom docks, transposed coordinates, out-of-perimeter
stations. This package consolidates that into one tested interface so the audit is a verdict
per station, not a re-run of someone's notebook.

## Install

```bash
pip install gbfs-toolkit            # from PyPI (when released)
pip install -e ".[dev]"            # from a local clone
```

Core depends only on numpy / scipy / pandas. Network discovery/fetch uses the optional
`[fetch]` extra (`requests`).

## Quick start

```python
import json, gbfs_toolkit as gb

raw = json.load(open("station_information.json"))
stations = gb.to_canonical_station_info(raw, system_id="velib")   # version-independent frame
verdict  = gb.audit_static(stations)                              # A1–A7 per station
clean    = stations[~verdict["flagged"].to_numpy()]              # quality filter in one line
```

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

Ingestion is normalised **once** into version-independent frames; audit and analysis then
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
formatting / dedup / I/O; your orchestrator (cron, Airflow…) owns the polling loop.
Requires the optional `[parquet]` extra (`pyarrow`).

```python
import gbfs_toolkit as gb

# in your poller (every N minutes):
gb.append_to_parquet(feed.station_status(), "lake/")   # Hive-partitioned by system_id/date

# in your analysis:
panel = gb.build_availability_panel("lake/", system_id="velib",
                                    start_time="2026-06-01", resample_freq="5min")
flow  = gb.calculate_net_flow(panel)   # Δ bikes/station + is_rebalancing_suspected
```

`build_availability_panel` filters partitions *before* loading (memory-bounded),
de-duplicates redundant polls (same `station_id` + `last_reported`), and optionally
resamples each station to a fixed cadence.

## Roadmap

- **v0.1** — canonical model, catalogue discovery, cross-version normalisation,
  static audit (A1–A7), CLI.
- **v0.2** — fetch/scrape (`GBFSFeed`, one-liners, `fetch_multiple`), dynamic audit
  (D1–D3), `station_state`, geo (`GeoKDTree`, `find_nearest_stations`), schema hardening.
- **v0.3 (this)** — longitudinal data lake: `append_to_parquet`,
  `build_availability_panel`, `calculate_net_flow`.
- **next** — advanced extras: `multimodal` (transit links), `cluster`
  (spatial / spectral / diurnal profiles), `osm` (BYOG infrastructure enrichment).

## How to cite

See [`CITATION.cff`](./CITATION.cff). The semantic taxonomy is from the
`gbfs-audit-catalogue` dataset paper (Fossé & Pallares, 2026).

## License

[MIT](./LICENSE). Affiliated with [CESI LINEACT (EA 7527)](https://lineact.cesi.fr), Montpellier, France.

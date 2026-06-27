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

- **StationInfo**: `system_id, station_id, name, lat, lon, capacity, station_type`
- **StationStatus**: `system_id, station_id, num_bikes_available, num_docks_available, last_reported, fetched_at, gbfs_version`
- **VehicleStatus**: `system_id, vehicle_id, lat, lon, is_reserved, is_disabled, fetched_at, gbfs_version`
- **AuditVerdict**: `system_id, station_id, A1…A7, flagged, reason`

## Roadmap

- **v0.1 (this)** — canonical model, catalogue discovery, cross-version normalisation,
  static audit (A1–A7), CLI.
- **v0.2** — spatial anomaly (spectral) + dynamic zombie/staleness detector; fetch + archive.
- **v0.3** — analysis-ready panels (availability, pseudo-flows, OD) and catalogue reproduction.

## How to cite

See [`CITATION.cff`](./CITATION.cff). The semantic taxonomy is from the
`gbfs-audit-catalogue` dataset paper (Fossé & Pallares, 2026).

## License

[MIT](./LICENSE). Affiliated with [CESI LINEACT (EA 7527)](https://lineact.cesi.fr), Montpellier, France.

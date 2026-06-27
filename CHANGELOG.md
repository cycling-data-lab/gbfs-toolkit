# Changelog

All notable changes are documented here ([Keep a Changelog](https://keepachangelog.com),
[SemVer](https://semver.org)).

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

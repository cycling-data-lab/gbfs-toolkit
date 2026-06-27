# Glossary

A shared vocabulary for the GBFS domain and for the concepts specific to this library. The aim is
a single terminological reference so that studies built on `gbfs-toolkit` interpret the same words
in the same way.

## Feeds and the standard

GBFS (General Bikeshare Feed Specification)
:   The open standard, maintained by MobilityData, for publishing real-time shared-mobility data.
    `gbfs-toolkit` ingests versions 1.x, 2.x and 3.x and normalises them to one model.

Endpoint
:   A single GBFS file such as `station_information.json` or `station_status.json`. The model joins
    several endpoints into the canonical frames.

Canonical frame
:   A version-independent pandas frame (StationInfo, StationStatus, VehicleStatus, AuditVerdict)
    that downstream code depends on. See [Data model](data-model.md).

## Spatial components

Physical station
:   A fixed docking station with a declared capacity and a set of docks.

Virtual station
:   An operator-defined parking location without physical docks. Its capacity is legitimately
    constant or null, which is why the capacity audits exclude it.

Free-floating vehicle
:   A vehicle parked outside any station, located by its own coordinates rather than a dock. A
    dockless system is composed mainly of free-floating vehicles.

Geofencing zone
:   An operator polygon that constrains where riding, parking or ending a trip is allowed. The real
    footprint of a free-floating system is its geofencing zones, not the convex hull of its
    stations.

## Computed metrics

Occupancy
:   The ratio bikes / (bikes + docks) at a station, vectorised and NaN-safe on the empty and
    dockless case. A descriptive measure of how full a station is.

Net flow
:   The observed change in available bikes at a station between two consecutive polls. It is an
    observed quantity, not an inferred trip count.

Turnover
:   The sum of the absolute net flow over a window, used as an activity proxy. By the aliasing
    argument below, it is a documented lower bound on true activity.

Stockout episode
:   A contiguous interval during which a station is empty or full, that is, an outage event of
    rentability or returnability.

## Methodological concepts

Aliasing (the polling Nyquist limit)
:   Any activity that cancels within a polling interval is invisible to the feed. A bike rented and
    returned to the same station between two snapshots yields a net flow of zero. Flow-based
    quantities are therefore a lower bound on true activity. Poll well below the timescale of the
    dynamics you want to measure, and always report your polling cadence.

Frozen station
:   A station whose value never changes over an active window while its `last_reported` stays
    fresh, the signature of a dead sensor. This is distinct from staleness (D3) and from a
    legitimate stockout.

Provenance manifest
:   A record produced by `generate_manifest` that lists a SHA-256 hash per Parquet partition plus a
    dataset summary, so a deposited dataset is citable and verifiable.

## Audit taxonomy

A1 to A7 (static anomalies)
:   The published static semantic audit applied per station on a single snapshot: out-of-domain
    inclusion, placeholder capacity, structural over-capacity, geospatial outlier, out-of-perimeter
    coverage, zero-capacity docks, and null capacity field. Thresholds are stated in the
    [Methodology](methodology.md).

D1 to D3 (dynamic anomalies)
:   The real-time audit applied on a live availability snapshot: negative counts (D1), structural
    over-capacity (D2), and staleness relative to the feed's advertised `ttl` (D3).

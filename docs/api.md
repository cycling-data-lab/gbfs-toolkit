# API reference

This reference is generated from the source docstrings (numpydoc style) and grouped
by module. A few conventions hold throughout:

- **Pure functions.** Every public function operates on the canonical pandas frames and
  returns a new frame or scalar. None mutate their inputs, so `df.pipe(gb.occupancy)`
  and method chaining are safe.
- **Fluent accessor.** Each public function is also reachable as a `.gbfs` accessor
  method on a DataFrame (for example `av.gbfs.occupancy()` or
  `info.gbfs.join_status(status)`). Single-frame operations map directly; two-frame
  operations take the second frame as the argument.
- **Optional features.** Capabilities that need heavier dependencies live behind extras:
  `[fetch]` (networking), `[parquet]` (the data lake), `[cluster]` (clustering),
  `[geo]` (geospatial and geofencing), `[osm]` (surroundings), and `[dtw]` (shape-aware
  diurnal clustering). Importing a function without its extra raises a clear error
  naming the missing package.

## Canonical data model

The version-independent schemas that every downstream function depends on. Column names
are the stable contract; raw GBFS JSON is never referenced past ingestion.

::: gbfs_toolkit.core.models
    options:
      show_root_heading: false
      show_root_toc_entry: false
      heading_level: 3

## Cross-version normalisation

Parsers that map GBFS 1.x, 2.x and 3.x payloads (including language-nested feeds) onto
the canonical frames.

::: gbfs_toolkit.io.normalize
    options:
      show_root_heading: false
      show_root_toc_entry: false
      heading_level: 3

## Static semantic audit (A1–A7)

The published quality taxonomy of Fossé and Pallares, applied per station on a static
frame. See the [Methodology](methodology.md) page for the exact thresholds.

::: gbfs_toolkit.audit.static
    options:
      show_root_heading: false
      show_root_toc_entry: false
      heading_level: 3

## Dynamic audit (D1–D3)

The real-time counterpart to the static audit: negative counts, structural
over-capacity, and staleness on a live availability snapshot.

::: gbfs_toolkit.audit.dynamic
    options:
      show_root_heading: false
      show_root_toc_entry: false
      heading_level: 3

## Discovery and catalogue

Resolve a system by place or id against the MobilityData global registry, with an
in-process cache and an offline fallback.

::: gbfs_toolkit.io.catalog
    options:
      show_root_heading: false
      show_root_toc_entry: false
      heading_level: 3

## Fetching and polite networking

`GBFSFeed`, the one-liners, and the polite-scraping primitives (pooled sessions,
retry and backoff, conditional GET). Requires the `[fetch]` extra.

::: gbfs_toolkit.io.fetch
    options:
      show_root_heading: false
      show_root_toc_entry: false
      heading_level: 3

## Longitudinal data lake

Turn a stream of snapshots into an analysis-ready panel: append, partition-pruned read,
de-duplication, resampling, observed net flow, coverage, and provenance manifests.
Requires the `[parquet]` extra.

::: gbfs_toolkit.io.timeseries
    options:
      show_root_heading: false
      show_root_toc_entry: false
      heading_level: 3

## Derived frame helpers

Generic derived-frame conveniences distilled from the lab's notebooks: occupancy and station
state, availability joins, network diffs, and vehicle-type and pricing joins.

::: gbfs_toolkit.analytics.frames
    options:
      show_root_heading: false
      show_root_toc_entry: false
      heading_level: 3

## Level of service and equity of access

Descriptive service-quality metrics: reliability, outage rates, recovery survival, docking
pressure, and capacity utilisation.

::: gbfs_toolkit.analytics.service
    options:
      show_root_heading: false
      show_root_toc_entry: false
      heading_level: 3

## Observed flow dynamics

Reconstructions of observed inventory change: cumulative drift, flow asymmetry, turnover proxy,
and aliasing vulnerability.

::: gbfs_toolkit.analytics.dynamics
    options:
      show_root_heading: false
      show_root_toc_entry: false
      heading_level: 3

## Temporal structure of usage

Temporal autocorrelation, peaking, diurnal profiles and bimodality, synchrony networks,
calendar context, and exogenous-series alignment.

::: gbfs_toolkit.analytics.temporal
    options:
      show_root_heading: false
      show_root_toc_entry: false
      heading_level: 3

## Inequality and system profiles

Strictly descriptive summaries and inequality algorithms (Gini, Theil, Lorenz, dynamic Gini)
plus system profiles and comparisons.

::: gbfs_toolkit.analytics.distribution
    options:
      show_root_heading: false
      show_root_toc_entry: false
      heading_level: 3

## Spatial statistics

Standard spatial algorithms (Moran's I global and local, Ripley's K and L, Clark–Evans,
Shannon entropy, fleet centre of mass, 2SFCA accessibility). Deterministic, numpy and scipy only.

::: gbfs_toolkit.spatial.analytics
    options:
      show_root_heading: false
      show_root_toc_entry: false
      heading_level: 3

## Station clustering

Spatial, topological, and behavioural clustering, including diurnal-profile typologies.
Requires the `[cluster]` extra (`[dtw]` for shape-aware clustering).

::: gbfs_toolkit.analytics.clustering
    options:
      show_root_heading: false
      show_root_toc_entry: false
      heading_level: 3

## Geospatial core

The shared great-circle k-nearest-neighbour index and the geometry helpers built on it.

::: gbfs_toolkit.spatial.geometry
    options:
      show_root_heading: false
      show_root_toc_entry: false
      heading_level: 3

## Geofencing and service areas

Operator polygons as a canonical GeoDataFrame, point-in-zone joins, and equal-area
density. Requires the `[geo]` extra.

::: gbfs_toolkit.spatial.geofencing
    options:
      show_root_heading: false
      show_root_toc_entry: false
      heading_level: 3

## Station surroundings (OSM)

The generic radius-summarisation primitive and the one-shot context frame combining
transit feeders and OSM features. Bring your own GeoDataFrame. Requires the `[osm]` extra.

::: gbfs_toolkit.spatial.osm
    options:
      show_root_heading: false
      show_root_toc_entry: false
      heading_level: 3

## Multimodal links

Spatial linkage between docks and transit stops (bring your own GTFS `stops`).

::: gbfs_toolkit.spatial.multimodal
    options:
      show_root_heading: false
      show_root_toc_entry: false
      heading_level: 3

## Fleet reconciliation

Reconcile the docked aggregate counts and the per-vehicle feed without double-counting,
and flag immobile free-floating units.

::: gbfs_toolkit.analytics.fleet
    options:
      show_root_heading: false
      show_root_toc_entry: false
      heading_level: 3

## Pandas accessor

The `.gbfs` DataFrame accessor that exposes the pure functions as fluent methods.

::: gbfs_toolkit.interfaces.accessor
    options:
      show_root_heading: false
      show_root_toc_entry: false
      heading_level: 3

## Diagnostics and bundled data

Environment reporting for bug reports, and the deterministic bundled sample used by the
docs, doctests, and offline tests.

::: gbfs_toolkit.interfaces.diagnostics
    options:
      show_root_heading: false
      show_root_toc_entry: false
      heading_level: 3

::: gbfs_toolkit.interfaces.datasets
    options:
      show_root_heading: false
      show_root_toc_entry: false
      heading_level: 3

## Errors

The `GBFSError` exception hierarchy.

::: gbfs_toolkit.core.errors
    options:
      show_root_heading: false
      show_root_toc_entry: false
      heading_level: 3

## Command line interface

The `gbfs audit` entry point, the semantic counterpart to the syntactic
`gbfs-validator`.

::: gbfs_toolkit.interfaces.cli
    options:
      show_root_heading: false
      show_root_toc_entry: false
      heading_level: 3

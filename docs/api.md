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

::: gbfs_toolkit.models
    options:
      show_root_heading: false
      show_root_toc_entry: false
      heading_level: 3

## Cross-version normalisation

Parsers that map GBFS 1.x, 2.x and 3.x payloads (including language-nested feeds) onto
the canonical frames.

::: gbfs_toolkit.normalize
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

::: gbfs_toolkit.catalog
    options:
      show_root_heading: false
      show_root_toc_entry: false
      heading_level: 3

## Fetching and polite networking

`GBFSFeed`, the one-liners, and the polite-scraping primitives (pooled sessions,
retry and backoff, conditional GET). Requires the `[fetch]` extra.

::: gbfs_toolkit.fetch
    options:
      show_root_heading: false
      show_root_toc_entry: false
      heading_level: 3

## Longitudinal data lake

Turn a stream of snapshots into an analysis-ready panel: append, partition-pruned read,
de-duplication, resampling, observed net flow, coverage, and provenance manifests.
Requires the `[parquet]` extra.

::: gbfs_toolkit.timeseries
    options:
      show_root_heading: false
      show_root_toc_entry: false
      heading_level: 3

## Analysis helpers

Research conveniences distilled from the lab's notebooks: stockout episodes, turnover,
flow balance, frozen-station detection, network diffs, and vehicle-type joins.

::: gbfs_toolkit.analysis
    options:
      show_root_heading: false
      show_root_toc_entry: false
      heading_level: 3

## Descriptive and spatial statistics

Strictly descriptive summaries and standard spatial and inequality algorithms
(Moran's I, Ripley's K and L, Clark–Evans, Gini, Theil, Lorenz). Deterministic,
numpy and scipy only.

::: gbfs_toolkit.stats
    options:
      show_root_heading: false
      show_root_toc_entry: false
      heading_level: 3

## Station clustering

Spatial, topological, and behavioural clustering, including diurnal-profile typologies.
Requires the `[cluster]` extra (`[dtw]` for shape-aware clustering).

::: gbfs_toolkit.cluster
    options:
      show_root_heading: false
      show_root_toc_entry: false
      heading_level: 3

## Geospatial core

The shared great-circle k-nearest-neighbour index and the geometry helpers built on it.

::: gbfs_toolkit.geo
    options:
      show_root_heading: false
      show_root_toc_entry: false
      heading_level: 3

## Geofencing and service areas

Operator polygons as a canonical GeoDataFrame, point-in-zone joins, and equal-area
density. Requires the `[geo]` extra.

::: gbfs_toolkit.geofencing
    options:
      show_root_heading: false
      show_root_toc_entry: false
      heading_level: 3

## Station surroundings (OSM)

The generic radius-summarisation primitive and the one-shot context frame combining
transit feeders and OSM features. Bring your own GeoDataFrame. Requires the `[osm]` extra.

::: gbfs_toolkit.osm
    options:
      show_root_heading: false
      show_root_toc_entry: false
      heading_level: 3

## Multimodal links

Spatial linkage between docks and transit stops (bring your own GTFS `stops`).

::: gbfs_toolkit.multimodal
    options:
      show_root_heading: false
      show_root_toc_entry: false
      heading_level: 3

## Fleet reconciliation

Reconcile the docked aggregate counts and the per-vehicle feed without double-counting,
and flag immobile free-floating units.

::: gbfs_toolkit.fleet
    options:
      show_root_heading: false
      show_root_toc_entry: false
      heading_level: 3

## Pandas accessor

The `.gbfs` DataFrame accessor that exposes the pure functions as fluent methods.

::: gbfs_toolkit.accessor
    options:
      show_root_heading: false
      show_root_toc_entry: false
      heading_level: 3

## Diagnostics and bundled data

Environment reporting for bug reports, and the deterministic bundled sample used by the
docs, doctests, and offline tests.

::: gbfs_toolkit.diagnostics
    options:
      show_root_heading: false
      show_root_toc_entry: false
      heading_level: 3

::: gbfs_toolkit.datasets
    options:
      show_root_heading: false
      show_root_toc_entry: false
      heading_level: 3

## Errors

The `GBFSError` exception hierarchy.

::: gbfs_toolkit.errors
    options:
      show_root_heading: false
      show_root_toc_entry: false
      heading_level: 3

## Command line interface

The `gbfs audit` entry point, the semantic counterpart to the syntactic
`gbfs-validator`.

::: gbfs_toolkit.cli
    options:
      show_root_heading: false
      show_root_toc_entry: false
      heading_level: 3

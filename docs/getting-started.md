# Getting started

## Requirements

`gbfs-toolkit` supports Python 3.10 and later. The core has a deliberately small dependency
footprint (numpy, scipy and pandas only), so it installs cleanly into a constrained research
environment. Heavier capabilities are isolated behind optional extras and lazy imports, so the
core never pulls in geopandas, pyarrow or scikit-learn unless you ask for them.

## Installation

```bash
pip install gbfs-toolkit                                  # core only
pip install "gbfs-toolkit[fetch,parquet]"                 # a typical collection setup
pip install "gbfs-toolkit[fetch,parquet,cluster,geo,osm,dtw]"   # everything
```

From a local clone, for development:

```bash
pip install -e ".[dev]"
```

## Extras matrix

Each extra unlocks one functional area. Installing a function's feature without its extra raises a
clear error naming the missing package, so an environment never fails silently.

| Extra | Installs | Unlocks |
|---|---|---|
| _(core)_ | numpy, scipy, pandas | Canonical data model, cross-version normalisation, static audit (A1–A7), CLI |
| `[fetch]` | requests | `GBFSFeed`, catalogue discovery, `fetch_multiple`, conditional GET, polite sessions |
| `[parquet]` | pyarrow | Longitudinal data lake: `append_to_parquet`, `build_availability_panel`, `calculate_net_flow`, manifests |
| `[cluster]` | scikit-learn | Spatial, spectral and diurnal-profile clustering |
| `[dtw]` | tslearn | Shape-aware diurnal clustering (`method="dtw"`) |
| `[geo]` | geopandas | Geofencing zones, point-in-zone joins, equal-area density, `to_gdf` |
| `[osm]` | geopandas | Station surroundings, `features_within`, `station_surroundings` |

## Verify the installation

```python
import gbfs_toolkit as gb

gb.show_versions()   # environment and dependency report, useful in bug reports
```

## Quickstart: audit a bundled feed offline

The package ships a small, deterministic GBFS snapshot of central Paris for docs, doctests and
offline tests. No network access is required.

```python
import gbfs_toolkit as gb

info, status = gb.load_example()                 # canonical (station_info, station_status)
verdict = gb.audit_static(info)                  # A1–A7 verdict, one row per station
clean = info[~verdict["flagged"].to_numpy()]     # keep the trustworthy stations
av = gb.join_availability(info, status)          # bikes and docks per station
av["occupancy"] = gb.occupancy(av)               # bikes / (bikes + docks), NaN-safe
```

Every public function is also a `.gbfs` accessor method and is pure, so method chaining and
`df.pipe(...)` both work:

```python
clean = info.gbfs.drop_flagged()
av = info.gbfs.join_status(status)
av.gbfs.occupancy()
```

## Quickstart: from your own feed

```python
import json
import gbfs_toolkit as gb

raw = json.load(open("station_information.json"))
stations = gb.to_canonical_station_info(raw, system_id="velib")   # version-independent frame
verdict = gb.audit_static(stations)                               # A1–A7 per station
```

## Command line

The CLI is the semantic counterpart to the syntactic `gbfs-validator`:

```bash
gbfs audit station_information.json --system-id velib --out verdict.csv
```

## Reproducibility

For a study that must be reproducible, pin the whole environment, not just `gbfs-toolkit`. The
audit thresholds and the canonical schema are frozen under semantic versioning, so a pinned version
reproduces the same verdicts.

```bash
pip install "gbfs-toolkit==1.1.0"
pip freeze > requirements.lock          # or use a Poetry / uv / conda lock file
```

Record the lock file alongside your analysis. When you deposit a collected dataset, also record its
provenance with `generate_manifest(lake_dir)` and quantify gaps with `coverage_report(panel)`, so a
reviewer can verify the data were frozen as described.

!!! note "Geospatial extras"
    The `[geo]` and `[osm]` extras install `geopandas`, which pulls in compiled geospatial
    libraries (GEOS, PROJ, GDAL). On most platforms the wheels install without a compiler, but on
    constrained or ARM environments a conda-based install of `geopandas` is the most reliable path.
    The core audit needs none of this.

## Next steps

- [Feature overview](guide.md): the full walkthrough of ingestion, the data lake, clustering, statistics, geofencing and fleet reconciliation.
- [Examples](examples.md): runnable end-to-end scripts, plus a fully offline [quickstart notebook](notebooks/quickstart.ipynb).
- [Methodology](methodology.md): the audit thresholds and the limits of what the toolkit can claim.
- [Data model](data-model.md): the canonical schema contract and its dtype guarantees.

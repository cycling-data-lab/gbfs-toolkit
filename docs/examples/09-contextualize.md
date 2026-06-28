# Contextualize with transit and weather

The most time-consuming task before a mobility regression is assembling the
covariates without a temporal leak. This builds a regression-ready frame: each
station tagged with nearby heavy transit (first/last-mile feeder evidence), an
exogenous weather series as-of-joined onto the panel with no look-ahead, and the
autocorrelation the model must respect. Self-contained, run in CI.

!!! info "Requirements"
    None for the demo (bundled stations + synthetic GTFS and weather). In practice,
    bring your own GTFS `stops` and weather/calendar frames (BYOD).

What the script does:

- Tags stations within a radius of a heavy transit stop with
  [`link_transit_stops`][gbfs_toolkit.link_transit_stops] (a plain `stops` frame, so
  no geospatial extra needed). For richer OSM context see
  [`enrich_with_osm`][gbfs_toolkit.enrich_with_osm] (`[osm]`).
- As-of joins an exogenous series onto the availability panel with
  [`join_exogenous_timeseries`][gbfs_toolkit.join_exogenous_timeseries] — a backward
  nearest match within a tolerance, so no future value leaks into a row.
- Reads the dependence structure with
  [`temporal_autocorrelation`][gbfs_toolkit.temporal_autocorrelation].

Run it:

```console
$ python examples/09_contextualize.py
```

Full source:

```python
--8<-- "examples/09_contextualize.py"
```

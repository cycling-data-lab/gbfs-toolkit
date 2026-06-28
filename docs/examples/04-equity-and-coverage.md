# Equity and coverage

Is the network spread fairly, or piled into a few downtown hubs? Two angles.
Capacity concentration asks whether the bikes are shared out or hoarded; spatial
dispersion asks whether the geography and the demand are clustered.

!!! info "Requirements"
    Extras: `[fetch]`, `[geo]`. A `gbfs.json` discovery URL.

What the script does:

- Measures capacity concentration with
  [`concentration_metrics`][gbfs_toolkit.concentration_metrics] (Gini, top-decile share).
- Measures spatial dispersion: density and Clark–Evans via
  [`coverage_stats`][gbfs_toolkit.coverage_stats], and clustering of occupancy via
  [`morans_i`][gbfs_toolkit.morans_i].
- Where geofencing zones are published, measures density against the real service
  area instead of a convex hull.

For richer equity and accessibility (Theil/Palma decomposition, E2SFCA, rebalancing
tension), see [Equity, accessibility & rebalancing](05-rigorous-audit.md).

Run it:

```console
$ python examples/04_equity_and_coverage.py https://example.com/gbfs.json
```

Full source:

```python
--8<-- "examples/04_equity_and_coverage.py"
```

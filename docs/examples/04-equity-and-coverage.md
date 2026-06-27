# Equity and coverage

Is the network spread fairly, or piled into a few downtown hubs? Two angles answer this. Capacity
concentration (Gini and Lorenz) asks whether the bikes are shared out or hoarded. Spatial
dispersion (density, Clark–Evans, Moran's I on occupancy) asks whether the geography and the demand
are clustered.

!!! info "Requirements"
    Extras: `[fetch]`, `[geo]`. Input: a `gbfs.json` discovery URL.

## Walkthrough

### 1. Discover the feed and read station information

```python
import gbfs_toolkit as gb

feed = gb.GBFSFeed.from_url(gbfs_url, system_id="mycity")
info = feed.station_information()
```

### 2. Measure capacity concentration

`concentration_metrics` reports the Gini index of capacity and the share held by the top decile of
stations. This is an equity lens, kept deliberately outside the A1–A7 quality audit, because
concentration is a property of network design rather than a feed defect.

```python
conc = gb.concentration_metrics(info)
print(f"capacity Gini {conc['gini']:.2f}, top 10% hold {conc['top_decile_share']:.0%}")
```

### 3. Measure spatial coverage against the real service area

If the feed publishes geofencing zones, density is measured against the operator's true service
area rather than a convex hull. This matters a great deal for free-floating systems, where a hull
badly overstates the footprint.

```python
zones = feed.geofencing_zones() if feed.has("geofencing_zones") else None
cov = gb.coverage_stats(info, zones=zones)
```

The report includes station density, mean nearest-neighbour distance, and the Clark–Evans
dispersion index.

### 4. Test whether low availability is geographically clustered

A live equity signal: `morans_i` measures spatial autocorrelation of occupancy across stations. A
value above the expected index indicates clustering.

```python
av = feed.availability()
av = av.assign(occ=av["num_bikes_available"] / (av["num_bikes_available"] + av["num_docks_available"]))
mi = gb.morans_i(av.dropna(subset=["occ", "lat", "lon"]), "occ")
```

!!! warning "These measures are descriptive"
    Clark–Evans is boundary-robust enough for an overall verdict, but Moran's I and Ripley's K are
    sensitive to edge effects on irregular real boundaries. Read the spatial-statistics section of
    the [Methodology](../methodology.md) before drawing strong conclusions.

## Run it

```bash
python 04_equity_and_coverage.py https://example.com/gbfs.json --system-id mycity
```

## Illustrative output

```text
capacity Gini 0.34, top 10% of stations hold 21% of capacity

318 stations over ~58.2 km² (5.5/km²), nearest-neighbour 214 m, Clark-Evans 0.81

occupancy Moran's I 0.27 (clustered, p=0.001)
```

## Interpreting the output

- **Capacity Gini** runs from 0 (every station equal) to 1 (capacity concentrated in a few hubs). The top-decile share tells the same story in plainer terms.
- **Clark–Evans** below 1 indicates spatial clustering, near 1 a random pattern, and above 1 dispersion.
- **Moran's I** above its expected value with a small p-value means low availability is geographically clustered right now, an equity signal worth acting on.

## Related

- API: `concentration_metrics`, `lorenz_curve` ([Inequality](../api.md#inequality-and-system-profiles)); `coverage_stats`, `morans_i` ([Spatial statistics](../api.md#spatial-statistics)).
- Concepts: the [spatial-statistics limits](../methodology.md) and the [equity metrics](../glossary.md#computed-metrics).

## Full script

```python title="examples/04_equity_and_coverage.py"
--8<-- "examples/04_equity_and_coverage.py"
```

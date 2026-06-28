# Analyse history

After a few weeks of collecting, turn the lake into something you can write about. Three questions
a reviewer will ask: how complete is the data, what does a typical day look like, and can the
stations be grouped by behaviour. Coverage comes first, because there is no point clustering the
rhythm of a station that was offline for half the month.

!!! info "Requirements"
    Extras: `[parquet]`, `[cluster]`. Input: a lake built up by [Collect a snapshot](02-collect-a-snapshot.md).

## Walkthrough

### 1. Build a local-time panel

Convert to local time before any daily aggregation. If the panel stays in UTC, the day boundary
falls at UTC midnight, which is mid-afternoon in the Americas, and rush hour lands at the wrong
hour.

```python
import gbfs_toolkit as gb

panel = gb.build_availability_panel(lake_dir, system_id="velib", target_tz="Europe/Paris")
```

### 2. Check coverage and keep the well-observed stations

```python
cov = gb.coverage_report(panel)
well_observed = cov.index[cov["uptime_pct"] > 80].get_level_values("station_id")
panel = panel[panel.index.get_level_values("station_id").isin(well_observed)]
```

### 3. Cluster the daily rhythms into typologies

`cluster_diurnal_profiles` groups stations by the shape of their 24-hour occupancy profile.
`normalize="zscore"` clusters on shape rather than level, and `n_clusters="auto"` chooses the
count by silhouette. `label_diurnal_typology` turns the clusters into named types such as morning
origin or recreational.

```python
typ = gb.cluster_diurnal_profiles(panel, n_clusters="auto", normalize="zscore")
labels = gb.label_diurnal_typology(typ.set_index(["system_id", "station_id"]))
print(labels.value_counts().to_string())
```

### 4. Rank the busiest stations by observed turnover

```python
flow = gb.calculate_net_flow(panel)
busiest = (
    flow.assign(activity=flow["net_flow"].abs())
    .groupby("station_id")["activity"].sum()
    .sort_values(ascending=False).head(5)
)
```

!!! warning "Turnover is a lower bound"
    Net flow is the observed change between two polls, so any activity that cancels within a
    polling interval is invisible. Treat turnover as a lower bound on true activity, and report
    your polling cadence. See [aliasing](../glossary.md#methodological-concepts) and the
    [Methodology](../methodology.md).

## Run it

```bash
python 03_analyze_history.py /data/velib_lake --system-id velib --tz Europe/Paris
```

## Illustrative output

```text
median uptime 96% (88% of stations above 90%)

station typologies:
morning_origin         142
evening_origin         118
recreational            74
stable                  41

most active stations (lower-bound turnover):
station_id
12109    3841
07002    3520
...
```

## Interpreting the output

- **Median uptime** sets how much of the panel you can trust. Here, stations below 80% uptime are dropped before any rhythm analysis.
- **Typologies** name each station by the shape of its day, for example morning origin versus recreational. This is the qualitative payoff of a longitudinal panel.
- **Turnover** ranks activity, but it is a lower bound (see the aliasing warning above), so report it as such rather than as a trip count.

## Related

- API: `build_availability_panel`, `coverage_report`, `cluster_diurnal_profiles`, `label_diurnal_typology`, `calculate_net_flow` ([Data lake](../reference/index.md), [Clustering](../reference/index.md)).
- Concepts: [aliasing](../glossary.md#methodological-concepts) and the local-time caveat in the [Methodology](../methodology.md).

## Full script

```python title="examples/03_analyze_history.py"
--8<-- "examples/03_analyze_history.py"
```

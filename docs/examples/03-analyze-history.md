# Analyse history

After a few weeks of collecting, turn the lake into something you can write about.
Three questions a reviewer will ask: how complete is the data, what does a typical
day look like, and can the stations be grouped by behaviour. Coverage comes first
— there is no point clustering rhythms from a station that was offline half the month.

!!! info "Requirements"
    Extras: `[parquet]`, `[cluster]`. Input: a Parquet lake built by the previous step.

What the script does:

- Builds the availability panel with
  [`build_availability_panel`][gbfs_toolkit.build_availability_panel].
- Reports per-station uptime and the longest gap with
  [`coverage_report`][gbfs_toolkit.coverage_report] (no imputation).
- Derives net flow ([`calculate_net_flow`][gbfs_toolkit.calculate_net_flow]) and
  clusters daily rhythms with
  [`cluster_diurnal_profiles`][gbfs_toolkit.cluster_diurnal_profiles] /
  [`label_diurnal_typology`][gbfs_toolkit.label_diurnal_typology].

Run it:

```console
$ python examples/03_analyze_history.py /data/velib_lake --system-id velib --tz Europe/Paris
```

Full source:

```python
--8<-- "examples/03_analyze_history.py"
```

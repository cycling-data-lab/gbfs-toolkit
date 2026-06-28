# Measure service reliability

Move the question from *quantity* (how many bikes) to *resilience* (how long a
station stays unusable). A descriptive Kaplan–Meier survival curve of stockout
durations is rare on bike-share, and it answers the question an operator's SLA
actually cares about. Self-contained (synthetic panel, no network), run in CI.

!!! info "Requirements"
    None (synthetic availability panel). Real panels come from
    [Collect a snapshot](02-collect-a-snapshot.md) and
    [Analyse history](03-analyze-history.md).

What the script does:

- Extracts stockout spells with
  [`stockout_episodes`][gbfs_toolkit.stockout_episodes] (contiguous empty/full time).
- Fits a descriptive Kaplan–Meier survival of episode duration with
  [`outage_survival`][gbfs_toolkit.outage_survival] — the right-censoring is stated,
  never imputed.
- Checks the collection cadence against the signal with
  [`aliasing_vulnerability`][gbfs_toolkit.aliasing_vulnerability] (is 15 minutes fast
  enough, or are micro-stockouts invisible?).
- Measures how peaked the day's activity is with
  [`temporal_concentration`][gbfs_toolkit.temporal_concentration].

Run it:

```console
$ python examples/08_service_reliability.py
```

Full source:

```python
--8<-- "examples/08_service_reliability.py"
```

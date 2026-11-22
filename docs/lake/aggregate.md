# aggregate: 15 minutes, an hour, a day

!!! warning "Experimental"
    Part of the experimental data-lake modules (2.1.0). See the [overview](index.md).

`aggregate_availability` turns minute-level snapshots into a station-by-bucket table whose columns
mean the same thing every time. The definitions are fixed:

| Column | Definition |
|---|---|
| `n_obs` | rows in the bucket, all of them (nothing is dropped or de-duplicated) |
| `n_valid` | rows with a bike count that are not flagged `both_zero_suspect`; every other column is computed from these |
| `bikes_mean`, `bikes_min`, `bikes_max`, `bikes_first`, `bikes_last` | the bike count over the valid rows, first and last in time order |
| `docks_mean`, `docks_min` | the same for free docks (empty if the operator does not publish them) |
| `pct_empty` | share of valid rows with no bike, in % |
| `pct_full` | share of valid rows where the station is full, in %: no free dock, or, if docks are not published and a `capacity` column exists, bikes at or above capacity |
| `pct_renting` | share of valid rows where `is_renting` is true, in % |
| `pct_both_zero` | share of **all** rows flagged `both_zero_suspect`, in % (counted here, excluded elsewhere) |
| `movement_volume` | sum of the absolute changes of the bike count between two consecutive valid rows of a station at most `max_pair_gap` (90 s) apart, in the bucket of the second |

`movement_volume` estimates how many bikes moved. A rental and a return within one poll cancel out
and are invisible, and it is **not a count of trips**.

## The conservation check

The sum of `n_obs` over all buckets is the number of input rows, at every frequency. This is the
property that makes the three levels describe the same data, and `aggregate_levels` verifies it
for you (`check_conservation` does it by hand).

Buckets are aligned on UTC. With `tz` (an IANA zone, or `{system_id: zone}`), the local wall-clock
start of each bucket and its UTC offset are added, so a local-time analysis can group on them
without redoing the clock change.

## Example

```python
import numpy as np
import pandas as pd

from gbfs_toolkit.aggregate import aggregate_availability, aggregate_levels, check_conservation

rng = np.random.default_rng(1)
t = pd.date_range("2026-03-28T22:00Z", periods=6 * 60, freq="min")   # spans Paris's clock change
snapshots = pd.DataFrame({
    "system_id": "demo", "station_id": "s1", "fetched_at": t,
    "num_bikes_available": rng.integers(0, 15, len(t)),
    "num_docks_available": rng.integers(0, 15, len(t)),
})

hourly = aggregate_availability(snapshots, "1h", tz="Europe/Paris")
print(hourly[["bucket_start_utc", "bucket_start_local", "utc_offset_min", "n_obs", "bikes_mean"]].head(4))

levels = aggregate_levels(snapshots)                  # 15m, 1h, 1d; each one checked
print({name: int(table["n_obs"].sum()) for name, table in levels.items()})
check_conservation(levels["15m"], snapshots)          # raises if an observation went missing
```

## API

::: gbfs_toolkit.aggregate

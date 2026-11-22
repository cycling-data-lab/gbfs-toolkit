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

## Large volumes

Besides a pandas frame, `aggregate_availability`, `aggregate_levels` and `check_conservation` take an
**Arrow table or dataset**, a **DuckDB relation**, or a **path**: a lake written by
[`store`](store.md), a folder of Parquet files (the day files and fragments of
[`collect`](collect.md) included), a file or a glob. The source is not loaded whole.

| `engine=` | What computes | Memory |
|---|---|---|
| `"auto"` (default) | a pandas frame stays on pandas; any other source goes to DuckDB if the `duckdb` extra is installed, otherwise to the pandas windows below | see below |
| `"duckdb"` | one SQL query over the source (windows, aggregates), spilling to a temporary folder | bounded by DuckDB (`GBFS_TOOLKIT_DUCKDB_MEMORY_LIMIT=4GB` caps it) |
| `"pandas"` | window by window (`chunk=`, one day by default, rounded up to a multiple of `freq` so that no bucket is split), carrying each station's last row across a boundary so the `movement_volume` of a pair that straddles two windows is kept | one window |

The engines **agree**: `n_obs` is conserved by each, counts and integer columns are identical, and
the other columns differ by floating-point rounding at most. Tests compare them on random data
(including repeated instants, missing counts and windows that cut a pair of rows). Two rows of the same
station at the same instant are ordered as the source lists them. The time column of a table, relation or
path must be a timestamp.

On a synthetic lake of 42 million rows (1000 stations, one poll a minute, 30 days) the numbers are in
`benchmarks/lake_volume.py`'s output; see the [roadmap](../roadmap.md) for the figures of the last run.

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

# The same table from an Arrow table, by windows of two hours (what runs without DuckDB)
import pyarrow as pa

table = pa.Table.from_pandas(snapshots, preserve_index=False)
by_windows = aggregate_availability(table, "1h", tz="Europe/Paris", engine="pandas", chunk="2h")
pd.testing.assert_frame_equal(hourly, by_windows, check_exact=False)
```

## API

::: gbfs_toolkit.aggregate

# Aggregate a month of snapshots

*Minute snapshots are too many to plot or join: give me one row per station and quarter of an hour.*
`aggregate_levels` returns 15-minute, hourly and daily tables whose columns mean the same thing
every time, and checks that each one holds exactly the input rows.

```python
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from gbfs_toolkit.aggregate import aggregate_levels, check_conservation
from gbfs_toolkit.store import write_lake

# A "month" of 20 stations, here 3 days at a poll a minute (86 400 rows) to keep the example quick.
rng = np.random.default_rng(1)
t = pd.date_range("2026-03-27", periods=3 * 1440, freq="min", tz="UTC")   # across Paris's clock change
n = 20
rows = pd.DataFrame({
    "system_id": "demo",
    "station_id": np.repeat([f"s{i:02d}" for i in range(n)], len(t)),
    "observed_at_utc": np.tile(t, n),
    "num_bikes_available": rng.integers(0, 20, len(t) * n),
    "num_docks_available": rng.integers(0, 20, len(t) * n),
})
lake = Path(tempfile.mkdtemp()) / "lake"
write_lake(rows, lake)

# 1. From the lake folder itself: DuckDB if installed, otherwise window by window in pandas.
#    The result is the same either way. Local columns follow the clock change.
levels = aggregate_levels(lake, time_col="observed_at_utc", tz="Europe/Paris")
print({name: len(table) for name, table in levels.items()})
print(levels["1h"].loc[levels["1h"]["station_id"] == "s00",
                       ["bucket_start_utc", "bucket_start_local", "utc_offset_min", "n_obs"]].iloc[[0, -1]])

# 2. The property that makes the three tables one dataset.
check_conservation(levels["15m"], lake)
assert {int(table["n_obs"].sum()) for table in levels.values()} == {len(rows)}

# 3. Choose the engine when you must.
by_windows = aggregate_levels(lake, time_col="observed_at_utc", engine="pandas", chunk="12h")
assert int(by_windows["1d"]["n_obs"].sum()) == len(rows)
```

What the columns mean (definitions are fixed): `n_obs` all rows in the bucket, `n_valid` the rows with a bike
count that are not flagged `both_zero_suspect`, then `bikes_*`, `docks_*`, `pct_empty`, `pct_full`,
`pct_renting` over the valid rows, and `movement_volume`, an estimate of how many bikes moved that is **not a
trip count**. See [aggregate](../lake/aggregate.md).

For a real month (a large system at a poll a minute is tens of millions of rows):

* collect with fragments and compact each closed day ([collect](../lake/collect.md)), or write a lake;
* pass the **folder** (`aggregate_levels("data/lake", time_col="observed_at_utc")`), not a frame read from it;
* on a small machine, `GBFS_TOOLKIT_DUCKDB_MEMORY_LIMIT=4GB` (and `GBFS_TOOLKIT_DUCKDB_THREADS`) cap DuckDB, which
  spills to a temporary folder it removes afterwards;
* `aggregate_availability(lake, "15min", ...)` gives a single level.

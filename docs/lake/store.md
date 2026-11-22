# store: a Parquet lake

!!! warning "Experimental"
    Part of the experimental data-lake modules (2.1.0). See the [overview](index.md).

A lake is plain Hive-partitioned Parquet, which DuckDB, Arrow, Spark and pandas all read without this
library:

```text
<root>/system_id=<id>/year=2026/month=03/data.parquet
<root>/lake.json                                        # format, time column, time zones
```

The system is the folder name and is not repeated inside the files; a reader gets it back as the
`system_id` column. Partitions follow the **UTC** year and month of the time column.

## Common columns

`harmonize` gives station and vehicle snapshots the same names whoever collected them:
`fetched_at` becomes `observed_at_utc`, `last_reported` becomes `last_reported_utc`, counts are
nullable integers, flags nullable booleans, ids text. Given an IANA zone (`tz=`, or `{system_id: zone}`)
it adds `observed_at_local` (the wall clock, no zone attached) and `utc_offset_min`, so the clock
change is recorded rather than recomputed.

## Writing

| `mode` | A partition that already holds data |
|---|---|
| `"append"` (default) | a new `part-<id>.parquet` is added: nothing is lost, writers never touch the same file; duplicates are kept |
| `"merge"` | existing files and new rows are combined, exact duplicates dropped, one `data.parquet` remains |
| `"replace"` | the partition holds only the new rows |

Files are written to a temporary name and renamed, so a reader never sees half a file.

`write_lake` takes a pandas frame, or, for volumes that do not fit in memory, an **Arrow table or
dataset, a DuckDB relation, or a path** (a folder of Parquet files such as the day files of
[`collect`](collect.md), a file, a glob, another lake). Those are written piece by piece: in `"append"`
mode one UTC day at a time (a file per day and system), in the other two modes one (system, month) at a
time, because merging or replacing needs the whole partition. The time column of such a source must be a
timestamp.

## Reading

`read_lake(root, systems=..., start=..., end=..., columns=...)` selects systems and the window
`start <= time < end` (UTC), skipping the folders outside it before opening any file. `output="arrow"`
returns a `pyarrow.Table` and `output="duckdb"` a lazy DuckDB relation over the selected files (nothing
loaded). For a lake larger than memory, hand the folder itself to
[`aggregate`](aggregate.md) and [`quality`](quality.md): they read it in place.

## DuckDB views

`duckdb_view_sql` returns a `CREATE VIEW` statement (no DuckDB needed to print it);
`register_duckdb_views` runs it on a connection (extra `duckdb`). `system_id` is text, `year` and
`month` integers, and a query that filters on them skips the other folders.

## Example

```python
import tempfile

import pandas as pd

from gbfs_toolkit.store import (
    duckdb_view_sql, harmonize, list_partitions, read_lake, write_lake)

times = pd.date_range("2026-01-31T22:00Z", periods=240, freq="min")      # crosses a month end
raw = pd.concat([
    pd.DataFrame({"system_id": system, "station_id": "s1", "fetched_at": times,
                  "num_bikes_available": 4, "num_docks_available": 6})
    for system in ("007", "harbor")
])
root = tempfile.mkdtemp()
write_lake(harmonize(raw, tz={"007": "Europe/Paris", "harbor": "Europe/Paris"}), root)
print(list_partitions(root))

feb = read_lake(root, systems=["007"], start="2026-02-01")
print(len(feb), feb["system_id"].unique(), feb["observed_at_local"].min())   # "007" keeps its zeros

print(duckdb_view_sql(root, "station_status"))
```

```python
import duckdb                                      # needs the duckdb extra
from gbfs_toolkit.store import register_duckdb_views

con = duckdb.connect()
register_duckdb_views(con, {"station_status": root})
print(con.sql("SELECT system_id, month, count(*) AS n FROM station_status GROUP BY ALL ORDER BY ALL"))
```

## API

::: gbfs_toolkit.store

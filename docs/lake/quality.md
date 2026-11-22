# quality: coverage, gaps and incidents

!!! warning "Experimental"
    Part of the experimental data-lake modules (2.1.0). See the [overview](index.md).

A collection is as useful as what you know about its holes. `gbfs_toolkit.quality` tells you,
**per system and UTC day**, how many of the expected polls arrived and why the others did not.

## Statuses

| Status | Meaning |
|---|---|
| `ok` | at least `ok_threshold_pct` (95 % by default, settable) of the expected polls arrived |
| `partial` | some arrived, not enough, and nothing explains it |
| `outage_collector` | the day overlaps a gap in the collection itself (no poll from **any** system for an hour or more) or an incident you declared |
| `outage_operator` | the collection was running, yet nothing came from this system |

A *poll* is a distinct slot (one minute by default; `poll_resolution="15min"` for a slower
cadence). **A day still being collected counts as partial**: pass `end=` yesterday to leave it out.

## Indicators that flag and never remove

`add_quality_indicators` adds three columns to station-status rows. **No row is dropped and there
is no cleaning pipeline**: what to do with a flagged row is your analysis's decision.

| Column | Meaning |
|---|---|
| `field_unsupported_by_operator` | the operator publishes `0` for a field for the whole month (docks of a dockless system, say): the field is named, and its column is blanked (`mask_unsupported=False` keeps it) |
| `both_zero_suspect` | zero bikes **and** zero free docks at a station of positive capacity: more often a placeholder than a state. Missing when a count or the capacity is unknown |
| `network_all_zero_anomaly` | in this poll more than 95 % of the system's rows are at zero on every field it publishes |

## The incident registry

An incident has an `incident_id`, `start_utc`, `end_utc` (empty: ongoing), a `scope` (`all` or
system identifiers separated by commas), a `cause` and a `summary`. The causes are `outage_collector`,
`outage_operator`, `unreadable_file` and `ambiguous_missing_value` (a period in which a value and
its absence cannot be told apart). You declare what you know; `detect_incidents` adds the collection
gaps and silent feeds it finds, with stable identifiers.

## Large volumes

`daily_coverage`, `find_collector_gaps`, `field_unsupported_by_operator`, `detect_incidents` and
`assess` take, besides a pandas frame, an Arrow table or dataset, a DuckDB relation or a path (a lake, a
folder of Parquet files, a file or a glob), and an `engine=` (`"auto"`, `"duckdb"`, `"pandas"`) with the
rules of [`aggregate`](aggregate.md#large-volumes). What they need from the rows is additive (polls per
system, day and slot; distinct minutes; non-empty and zero values per system and period), so DuckDB, or
batches of pandas, give the same tables as the frame does. `add_quality_indicators` returns a row per input
row and stays on pandas frames.

`QualityReport` (what `assess` returns) reads like the pair of tables it holds: `report.coverage` and
`report.incidents`, `report["coverage"]`, `report.to_frames()`, `report.to_frame()` (the coverage). The
columns and logical types of the tables are `COVERAGE_COLUMNS` / `COVERAGE_DTYPES` and
`INCIDENT_COLUMNS` / `INCIDENT_DTYPES`.

## Example

```python
import numpy as np
import pandas as pd

from gbfs_toolkit.quality import (
    add_incident, add_quality_indicators, assess, read_incidents, write_incidents)

def poll(system, start, minutes, bikes=3, docks=5):
    t = pd.date_range(start, periods=minutes, freq="min", tz="UTC")
    return pd.DataFrame({"system_id": system, "station_id": "s1", "fetched_at": t,
                         "num_bikes_available": bikes, "num_docks_available": docks, "capacity": 10})

snapshots = pd.concat([
    poll("alpha", "2026-03-01", 3 * 1440),               # complete for three days
    poll("beta", "2026-03-01", 1440),                    # beta goes silent after the first day
    poll("gamma", "2026-03-01", 600), poll("gamma", "2026-03-01T16:00", 480 + 2 * 1440),  # 6-hour hole
])
snapshots = snapshots[~((snapshots.system_id != "gamma")
                        & (snapshots.fetched_at.between("2026-03-01T10:00Z", "2026-03-01T15:59Z")))]

known = add_incident(None, "migration", "2026-02-01", "2026-02-03",
                     cause="ambiguous_missing_value", summary="Older collector wrote 0 for a missing count.")
report = assess(snapshots, known_incidents=known, end="2026-03-03")
print(report.coverage.pivot(index="date_utc", columns="system_id", values="status"))
print(report.incidents[["incident_id", "scope", "cause"]].to_string(index=False))
print(report.summary()["days_by_status"])

write_incidents(report.incidents, "incidents.json")      # .csv works too
assert len(read_incidents("incidents.json")) == len(report.incidents)

flagged = add_quality_indicators(poll("delta", "2026-03-01", 4, bikes=[0, 0, 4, 2], docks=[0, 0, 3, 3]))
print(flagged[["num_bikes_available", "both_zero_suspect"]])
```

## API

::: gbfs_toolkit.quality

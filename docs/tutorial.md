# Tutorial: from a feed to a frozen release

A walk through the whole chain on synthetic data, offline, in about ten minutes: collect, compact,
store, check, aggregate, read trips, freeze, verify. Every block runs (the test suite executes them) and
builds on the one before. The modules involved are the [data-lake modules](lake/index.md), which are
experimental; the [recipes](recipes/index.md) answer one task each.

You need `pip install "gbfs-toolkit[parquet,duckdb]"` (DuckDB is optional: without it the same functions
run in pandas, window by window).

## 1. Collect

`Collector` polls feeds politely. Here the network is replaced by a function returning the documents a
feed would, which is also how the module's own tests work; leave `get_json` out to use HTTP.

```python
import tempfile
from pathlib import Path

import pandas as pd

from gbfs_toolkit.collect import Collector, compact_collected, read_collected

work = Path(tempfile.mkdtemp())
discovery = {"version": "2.3", "data": {"en": {"feeds": [
    {"name": "station_status", "url": "https://example.org/status.json"}]}}}
status = {"ttl": 0, "data": {"stations": [
    {"station_id": "7", "num_bikes_available": 4, "num_docks_available": 8, "is_renting": True},
    {"station_id": "8"}]}}                               # a station that publishes nothing
docs = {"https://example.org/gbfs.json": discovery, "https://example.org/status.json": status}

clock = iter(pd.date_range("2026-03-01T10:00Z", periods=3, freq="min"))
collector = Collector({"harbor": "https://example.org/gbfs.json"}, work / "collected",
                      user_agent="tutorial/1.0 (mailto:me@example.org)",
                      get_json=docs.__getitem__, min_interval=0, now=lambda: next(clock))
for _ in range(3):
    collector.poll_once()

snaps = read_collected(work / "collected")
print(len(snaps), snaps["num_bikes_available"].isna().tolist())    # station 8: empty, never 0
```

Each poll wrote a small fragment; nothing already written was touched. Gather the fragments of a closed
day into one file (here we also compact "today", which a real run leaves alone):

```python
print(compact_collected(work / "collected", include_today=True)[["system_id", "day", "fragments", "rows"]])
assert compact_collected(work / "collected", include_today=True).empty       # idempotent
```

## 2. Store

Real collections are bigger, so from here we use a larger synthetic one: three systems over a week, with a
collection outage for everyone on the 3rd and one system silent from the 5th. `write_lake` partitions it
by system, year and month, in plain Hive layout that DuckDB, Arrow and pandas read without this library.

```python
import numpy as np

from gbfs_toolkit.store import harmonize, list_partitions, write_lake

rng = np.random.default_rng(0)
frames = []
for system, keep in (("harbor", 0.99), ("lakeside", 0.8), ("hilltop", 0.99)):
    t = pd.date_range("2026-03-01", periods=7 * 1440, freq="min", tz="UTC")
    t = t[(t < "2026-03-03T02:00Z") | (t >= "2026-03-03T07:00Z")]      # the collector was down
    if system == "hilltop":
        t = t[t < "2026-03-05T00:00Z"]                                 # the operator went silent
    t = t[rng.random(len(t)) < keep]
    for station in ("s1", "s2"):
        frames.append(pd.DataFrame({
            "system_id": system, "station_id": station, "fetched_at": t,
            "num_bikes_available": rng.integers(0, 15, len(t)),
            "num_docks_available": rng.integers(0, 15, len(t)), "capacity": 20}))
raw = pd.concat(frames, ignore_index=True)

lake = work / "lake"
write_lake(harmonize(raw, tz="Europe/Paris"), lake)
print(list_partitions(lake)[["system_id", "year", "month", "files"]])
```

A folder of day files like the one in step 1 can go into a lake the same way, without loading it:
`write_lake(work / "collected" / "station_status", lake)`.

## 3. Check

`assess` says, per system and day, how many of the expected polls arrived and why a day fell short. It
reads the lake folder in place.

```python
from gbfs_toolkit.quality import assess

report = assess(lake, time_col="observed_at_utc", end="2026-03-07")
print(report.summary()["days_by_status"])
print(report.incidents[["incident_id", "cause", "scope"]].to_string(index=False))
assert (report.coverage["status"] != "ok").any()
```

## 4. Aggregate

Fifteen-minute, hourly and daily tables with fixed definitions, from the folder, with a check that each
level holds exactly the rows it was made from. DuckDB computes when installed; `engine="pandas"` gives the
same table window by window.

```python
from gbfs_toolkit.aggregate import aggregate_levels

levels = aggregate_levels(lake, time_col="observed_at_utc", tz="Europe/Paris")
print({name: len(table) for name, table in levels.items()})
assert {int(table["n_obs"].sum()) for table in levels.values()} == {len(raw)}
same = aggregate_levels(lake, time_col="observed_at_utc", tz="Europe/Paris", engine="pandas")
assert (same["1h"]["n_obs"] == levels["1h"]["n_obs"]).all()
```

## 5. Trips

Operators also publish trips. `read_trips` reads the formats it knows into one table, with explicit time
zones, clock-change flags and no personal field.

```python
import io

from gbfs_toolkit.trips import read_trips

csv = ("ride_id,started_at,ended_at,start_station_id,end_station_id,member_casual\n"
       "r1,2026-03-01 08:00:00,2026-03-01 08:12:00,s1,s2,member\n")
trips = read_trips(io.BytesIO(csv.encode()), tz="Europe/Paris", network="harbor")
print(trips[["ride_id", "started_at", "duration_s"]])
```

## 6. Freeze and verify

Cut the closed period, with its coverage and incidents, a data package, a README and checksums; then
verify the folder as someone who downloads it would. Nothing is uploaded and there is no default licence.

```python
from gbfs_toolkit.release import freeze_release, verify_release

info = freeze_release(lake, work / "release", name="demo-2026-03",
                      start="2026-03-01", end="2026-03-07", license="CC0-1.0")
print(info["rows"], info["systems"])
print(sorted(p.name for p in (work / "release").iterdir()))
print(verify_release(work / "release", deep=True)["ok"])
```

Deposit the folder yourself (Zenodo, for instance), and see the recipe
[Freeze a version for Zenodo](recipes/freeze-for-zenodo.md) for what to do next.

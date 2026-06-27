# Collect a snapshot

One collection run, meant to be driven by an external scheduler rather than a loop inside the
script. It polls `station_status` once, appends it to a Hive-partitioned Parquet lake, and
remembers the feed's ETag so the next run can skip the download when nothing has changed. Run it
every few minutes for a few weeks and you have a panel.

!!! info "Requirements"
    Extras: `[fetch]`, `[parquet]`. Inputs: a MobilityData catalogue id and a lake directory.

!!! note "The toolkit collects, your orchestrator schedules"
    Keeping the schedule outside the library is deliberate. The toolkit owns formatting,
    de-duplication and I/O; cron, Airflow or systemd own the polling loop.

## Walkthrough

### 1. Resolve the system

```python
import gbfs_toolkit as gb

feed = gb.GBFSFeed.from_system_id("velib")
status_url = feed.feeds.get("station_status")
```

### 2. Conditional GET, so an unchanged snapshot is not re-downloaded

The previous run's ETag is stored next to the lake. `fetch_feed_json` sends it as
`If-None-Match`; the server answers HTTP 304 when nothing changed, which surfaces as
`GBFSNotModified`.

```python
session = gb.build_session()
try:
    resp = gb.fetch_feed_json(status_url, session=session, etag=etag)
except gb.GBFSNotModified:
    return  # nothing new this run
```

### 3. Normalise to the canonical schema

Stamp the collection time as timezone-aware UTC so snapshots from any city merge unambiguously.

```python
import pandas as pd

status = gb.to_canonical_station_status(
    resp.data, system_id="velib", fetched_at=pd.Timestamp.now(tz="UTC")
)
```

### 4. Append to the lake, then persist the new ETag

`append_to_parquet` writes append-only, partitioned by `system_id` and `date`, which keeps later
panel reads memory-bounded.

```python
gb.append_to_parquet(status, lake_dir)
if resp.etag:
    state_file.write_text(resp.etag)
```

## Run it

A single run, then the cron line that repeats it every two minutes:

```bash
python 02_collect_snapshot.py velib /data/velib_lake
```

```cron
*/2 * * * * python 02_collect_snapshot.py velib /data/velib_lake
```

## Illustrative output

```text
velib: appended 1473 rows
```

A run that hits HTTP 304 prints nothing and exits, leaving the lake unchanged.

## Full script

```python title="examples/02_collect_snapshot.py"
--8<-- "examples/02_collect_snapshot.py"
```

# collect: a polite collector

!!! warning "Experimental"
    Part of the experimental data-lake modules (2.1.0). See the [overview](index.md).

`gbfs_toolkit.collect.Collector` polls the station (and vehicle) feeds of some systems and writes
what they publish. You call it; it never starts anything by itself.

## What it does and refuses to do

| | |
|---|---|
| **It identifies itself** | `user_agent` is required, with no default. Give one that tells an operator whom to write to: `"my-lab-gbfs/1.0 (mailto:me@example.org)"`. |
| **It respects `ttl`** | A GBFS document says how long it stays fresh. The collector will not ask again before that, nor before `min_interval` (1 s by default). `respect_ttl=False` exists for tests and for a feed whose `ttl` you know to be wrong; you then own the load you put on it. |
| **It backs off** | A feed that fails is left alone for 2, 4, 8 ... seconds (capped by `max_backoff`); HTTP retries of 429 and 5xx honour `Retry-After`. After five failures in a row the feed's URL is looked up again. |
| **It uses conditional requests** | `ETag` and `Last-Modified` are sent back; a `304` is not stored again. |
| **It never invents a value** | A field the feed leaves out is stored **empty and typed**: `Int64` counts, `boolean` flags, `float64` coordinates. Never `0`, never `True`. |
| **It writes atomically** | One Parquet file per system and UTC day, written to a temporary name and renamed. |
| **One bad feed does not stop the rest** | A failure is logged and reported in the result table, never raised. |

!!! note "A difference with `to_canonical_station_status`"
    The older `gbfs_toolkit.to_canonical_station_status` turns a missing `is_renting` into `True`
    (and `to_canonical_vehicles` a missing `is_disabled` into `False`): convenient for a one-off
    look, wrong for a collection, where a station that publishes nothing must not look open.
    `collect` keeps the gap. If you have data from an older collector that wrote those defaults,
    declare it as an `ambiguous_missing_value` incident in [quality](quality.md).

## Layout

```text
<out_dir>/station_status/<system_id>/2026-03-01.parquet
<out_dir>/vehicle_status/<system_id>/2026-03-01.parquet
<out_dir>/metadata/<system_id>/<feed>/<day>.parquet      # with poll_metadata, see history
```

A day file is rewritten whole at each poll: simple and safe for a few hundred stations every
minute. For much larger volumes, move the day files into a [lake](store.md) once a day.

## Example

The getter below stands in for the network, which is how the tests of the module work too; leave
`get_json` out to use HTTP (needs `pip install "gbfs-toolkit[fetch,parquet]"`).

```python
import tempfile

from gbfs_toolkit.collect import Collector, read_collected

docs = {
    "https://example.org/gbfs.json": {"version": "2.3", "data": {"en": {"feeds": [
        {"name": "station_status", "url": "https://example.org/status.json"},
        {"name": "free_bike_status", "url": "https://example.org/bikes.json"}]}}},
    "https://example.org/status.json": {"ttl": 60, "data": {"stations": [
        {"station_id": "7", "num_bikes_available": 4, "num_docks_available": 8, "is_renting": True},
        {"station_id": "8"}]}},                       # a station that publishes nothing
    "https://example.org/bikes.json": {"ttl": 0, "data": {"bikes": [
        {"bike_id": "b1", "lat": 43.61, "lon": 3.87}]}},
}

out = tempfile.mkdtemp()
collector = Collector(
    {"demo": "https://example.org/gbfs.json"}, out,
    user_agent="docs-example/1.0 (mailto:me@example.org)",
    feeds=("station_status", "vehicle_status"),
    get_json=docs.__getitem__,          # offline; omit to use HTTP
    min_interval=0,
)
print(collector.poll_once()[["feed", "outcome", "rows"]])
print(collector.poll_once()[["feed", "outcome"]])    # the 60 s ttl: station_status is skipped

stations = read_collected(out)
print(stations[["station_id", "num_bikes_available", "is_renting"]])   # station 8: empty, not 0
```

A bounded loop in your own process (`Ctrl-C` ends it cleanly):

```python
# not run in the tests (it would take an hour)
collector.run(interval=60, duration=3600)        # one hour, a poll a minute
```

The same from the shell: see [the command line](cli.md).

## API

::: gbfs_toolkit.collect

# trips: published trip files

!!! warning "Experimental"
    Part of the experimental data-lake modules (2.1.0). See the [overview](index.md).

Several operators publish one row per trip as open data, each in its own shape. `gbfs_toolkit.trips`
reads these families into one table, `TRIP_COLUMNS`:

| Format | Operators | Files |
|---|---|---|
| `lyft` | Lyft / Motivate: Citi Bike, Divvy, Bluebikes, Bay Wheels, Capital Bikeshare, Nice Ride... | the current files (`ride_id, started_at, ...`) and the older ones (`tripduration, starttime, ...`; `trip_id, from_station_id, ...`; `Start date, Start station number, ...`) |
| `urban_sharing` | Urban Sharing: Oslo, Bergen, Trondheim | ISO 8601 times with an offset, coordinates inline |
| `bts` | Bicycle Transit Systems: Indego, Metro Bike Share | the published duration changes unit between years, so it is recomputed from the two times |

`ride_id` is the operator's own trip identifier, never a user's.

!!! note "Formats not covered"
    No other format is guessed. In particular there is **no reader for French operators' files**
    (for instance Vélomagg, the Montpellier system): no verified description of their columns was available,
    and a guessed reader would silently mislabel data. If you have one, describe its columns once with
    `TripFormat` (below), and consider contributing it with a sample file.

## Time zones are explicit

Most files publish *local* wall-clock times without a zone, so `tz=` (an IANA name such as
`"America/Chicago"`) is **required** for them; there is no default, because UTC would be a silent mistake.
Times come out tz-aware UTC. A local time that does not exist (the hour skipped in spring) is moved to the
first instant after the change, and one that happens twice (the repeated hour in autumn) is read as the
second, standard-time occurrence. Both are flagged in `started_at_tz_flag` and `ended_at_tz_flag`
(`"nonexistent"`, `"ambiguous"`), never fixed silently.

## No personal data

Birth year, gender and bike number are dropped, and the schema has no user identifier. `member_type` is
only `member` or `casual`.

## Example

```python
import io

import pandas as pd

from gbfs_toolkit.trips import TripFormat, detect_format, normalize_trips, read_trips

current = (
    "ride_id,rideable_type,started_at,ended_at,start_station_id,end_station_id,member_casual\n"
    "r1,electric_bike,2024-03-10 01:50:00,2024-03-10 03:10:00,S1,S2,member\n"      # across the spring change
    "r2,classic_bike,2024-11-03 01:30:00,2024-11-03 01:45:00,S2,,casual\n"          # in the repeated hour
)
trips = read_trips(io.BytesIO(current.encode()), tz="America/New_York", network="demo")
print(trips[["ride_id", "started_at", "duration_s", "started_at_tz_flag", "end_station_id"]])

legacy = pd.DataFrame({"tripduration": [600], "starttime": ["2019-06-01 07:00:00"],
                       "stoptime": ["2019-06-01 07:10:00"], "usertype": ["Subscriber"],
                       "birth year": [1980], "gender": [1], "bikeid": [7]})
assert detect_format(legacy.columns) == "lyft"
print(normalize_trips(legacy, tz="America/New_York").columns.tolist())   # no personal fields

# A format of your own: describe the columns once.
mine = TripFormat("mycity", {"ride_id": ["id"], "started_at": ["debut"], "ended_at": ["fin"]},
                  times_have_offset=True)
raw = pd.DataFrame({"id": [1], "debut": ["2025-01-01T10:00:00+01:00"], "fin": ["2025-01-01T10:05:00+01:00"]})
print(normalize_trips(raw, mine)[["started_at", "duration_s"]])
```

Large files: `iter_trips(path, tz=..., chunksize=500_000)` yields normalised chunks, and a `.zip` (nested zips
included) is read member by member.

## API

::: gbfs_toolkit.trips

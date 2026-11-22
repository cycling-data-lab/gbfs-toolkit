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
| `velomagg` | Vélomagg (Montpellier Méditerranée Métropole, open data under the ODbL) | `Departure, Return, Departure station, Return station, Covered distance (m), Duration (sec.), Manager, ...`: local times, the station number in front of the name, text that may be double-encoded |

`ride_id` is the operator's own trip identifier, never a user's.

!!! note "Formats not covered"
    A format is added only when its columns have been checked against a real file; none is guessed,
    because a guessed reader would silently mislabel data. If you have another one, describe its columns
    once with `TripFormat` (below), and consider contributing it with a sample file.

## Vélomagg

The Montpellier file publishes one row per trip, with the local time and the operator's station
numbers. `read_trips(path, tz="Europe/Paris")` gives:

* `start_station_id` / `start_station_name` from `"002 Comédie"` (the number, then the name; a station
  with no number keeps its name and has an empty id), the same for the return;
* text repaired when the file is UTF-8 read as Latin-1 and encoded again (`ComÃ©die` becomes `Comédie`;
  a value that is already right is left alone);
* `distance_m` from `Covered distance (m)` and `duration_s` from `Duration (sec.)`, as published (the
  duration is not recomputed from the two times: it differs by a few seconds from them);
* `ended_at` empty when the file has no return time (a trip still open when the file was cut);
* **`is_operator_staff`**, a nullable boolean carried from the `Manager` column: `True` where the operator
  marks the trip as made by its own staff, `False` where it does not, empty where the file is empty. The
  flag is the publisher's, carried as published; this module does nothing else with it. The other formats
  leave it empty.

!!! warning "The account column is never read"
    The file has an account number (`new_account`) that tells two trips of one person apart, and a bike
    number. Neither is carried over, and there is no option to keep them: a column that is not in the
    format cannot appear in the result. A test checks that no value of the account column reaches the
    output, whichever reader or format is used. Times and stations can still identify a person when
    combined, so read the licence and the publisher's terms before releasing anything made from the file.

## Time zones are explicit

Most files publish *local* wall-clock times without a zone, so `tz=` (an IANA name such as
`"America/Chicago"`) is **required** for them; there is no default, because UTC would be a silent mistake.
Times come out tz-aware UTC. A local time that does not exist (the hour skipped in spring) is moved to the
first instant after the change, and one that happens twice (the repeated hour in autumn) is read as the
second, standard-time occurrence. Both are flagged in `started_at_tz_flag` and `ended_at_tz_flag`
(`"nonexistent"`, `"ambiguous"`), never fixed silently.

## No personal data

Birth year, gender, bike number and account number are dropped, and the schema has no user identifier.
`member_type` is only `member` or `casual`.

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

```python
# Vélomagg: two invented rows in the published shape (the account column is in the file, not in the result)
velomagg = (
    "Departure,Return,Bike,Departure station,Return station,Covered distance (m),Duration (sec.),"
    "Manager,new_account\n"
    "2025-03-29 23:55:38,2025-03-30 00:12:27,230,001 Place Exemple,002 CafÃ© de la Gare,2909,1001,False,900001\n"
    "2025-06-01 08:00:00,2025-06-01 08:10:00,619,001 Place Exemple,001 Place Exemple,0,600,True,900002\n"
)
ride = read_trips(io.BytesIO(velomagg.encode("utf-8")), tz="Europe/Paris", network="velomagg")
print(ride[["start_station_id", "end_station_name", "distance_m", "is_operator_staff"]])
assert "new_account" not in ride.columns and "900001" not in ride.astype(str).to_csv()
```

Large files: `iter_trips(path, tz=..., chunksize=500_000)` yields normalised chunks, and a `.zip` (nested zips
included) is read member by member.

## API

::: gbfs_toolkit.trips

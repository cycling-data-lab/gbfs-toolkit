# Read published trips

*An operator publishes a trip file; I want one table, with times I can trust and no personal data.*
`read_trips` reads Lyft/Motivate files (Citi Bike, Divvy, Bluebikes...), Urban Sharing, Bicycle Transit
Systems and the Vélomagg file of Montpellier into the same columns (`TRIP_COLUMNS`), and `TripFormat`
describes any other. Nothing is guessed: a format is added when its columns have been checked on a real
file.

```python
import io

import pandas as pd

from gbfs_toolkit.trips import TRIP_COLUMNS, TripFormat, read_trips

# 1. A file that publishes local times without a zone: tz= is required (there is no default),
#    and the hours a clock change makes odd are flagged, not fixed silently.
current = (
    "ride_id,rideable_type,started_at,ended_at,start_station_id,end_station_id,member_casual\n"
    "r1,electric_bike,2024-03-10 01:50:00,2024-03-10 03:10:00,S1,S2,member\n"
    "r2,classic_bike,2024-11-03 01:30:00,2024-11-03 01:45:00,S2,,casual\n"
)
trips = read_trips(io.BytesIO(current.encode()), tz="America/New_York", network="demo")
print(trips[["ride_id", "started_at", "duration_s", "member_type", "started_at_tz_flag"]])

# 2. The Vélomagg file (Montpellier, open data): the station number is split from the name, text
#    that was encoded twice is repaired, the account column is never read, and the operator's own
#    staff flag is carried as a nullable boolean. (Two invented rows in the published shape.)
velomagg = (
    "Departure,Return,Bike,Departure station,Return station,Covered distance (m),Duration (sec.),"
    "Manager,new_account\n"
    "2025-06-01 08:00:00,2025-06-01 08:12:00,230,001 Place Exemple,002 CafÃ© de la Gare,2909,700,False,900001\n"
    "2025-06-01 09:00:00,2025-06-01 09:05:00,619,002 CafÃ© de la Gare,001 Place Exemple,800,290,True,900002\n"
)
rides = read_trips(io.BytesIO(velomagg.encode("utf-8")), tz="Europe/Paris", network="velomagg")
print(rides[["start_station_id", "end_station_name", "distance_m", "is_operator_staff"]])
assert list(rides.columns) == TRIP_COLUMNS and "900001" not in rides.astype(str).to_csv()

# 3. Another format: describe its columns once.
mine = TripFormat("mycity", {"ride_id": ["id"], "started_at": ["debut"], "ended_at": ["fin"]},
                  times_have_offset=True)
raw = pd.DataFrame({"id": [1], "debut": ["2025-01-01T10:00:00+01:00"], "fin": ["2025-01-01T10:05:00+01:00"]})
print(read_trips(io.BytesIO(raw.to_csv(index=False).encode()), mine)[["started_at", "duration_s"]])
```

Things to know:

* **Time zones.** Times come out tz-aware UTC. `started_at_tz_flag` and `ended_at_tz_flag` say `nonexistent`
  (the skipped hour in spring) or `ambiguous` (the repeated hour in autumn).
* **No personal data.** Birth year, gender, bike number and account number are dropped, and the schema has no
  user identifier. The Vélomagg account column cannot be kept. Times and stations combined can still
  identify someone: check the publisher's terms before releasing anything built from a trip file.
* **`is_operator_staff`** is the publisher's flag for trips made by its own staff, carried as published; the
  other formats leave it empty. This module does nothing else with it.
* **Big files.** `iter_trips(path, tz=...)` yields normalised chunks; a `.zip` (nested zips included) is read
  member by member.

See [trips](../lake/trips.md).

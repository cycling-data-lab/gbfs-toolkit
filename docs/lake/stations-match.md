# stations.match: following station identifiers

!!! warning "Experimental"
    Part of the experimental data-lake modules (2.1.0). See the [overview](index.md).

Operators renumber stations, re-issue ids when they change platform, and move a dock a few metres.
A study that spans two periods needs to know which station of the first is which of the second.
`match_stations(old, new)` pairs them **one to one**, within a system, in three passes, and labels
each pair with the rule that made it:

| `match_method` | Rule |
|---|---|
| `same_id` | the identifier exists in both tables (and the stations are within `same_id_far_m`, 300 m) |
| `same_id_far` | same identifier, more than `same_id_far_m` apart: probably not the same place, check it |
| `same_name` | among what is left: equal *normalised* names (case, accents, punctuation and a leading `"042 - "` ignored) within `name_radius_m` (150 m) |
| `nearest` | among what is left: within `radius_m` (100 m), closest first |
| `none` | in `old` only: the station disappeared |
| `only_new` | in `new` only: it appeared |

Keep the safe pairs (`same_id`, `same_name`) and look at the others. Two systems that reuse the same
numbers never match each other, and ids stay text so a leading zero survives. `id_continuity` summarises,
for consecutive periods, how much of the numbering survives.

## Example

```python
import pandas as pd

from gbfs_toolkit.stations.match import id_continuity, match_stations

def stations(rows):
    return pd.DataFrame(rows, columns=["system_id", "station_id", "name", "lat", "lon"])

y2025 = stations([("harbor", "1", "Gare", 45.760, 4.860), ("harbor", "2", "Mairie", 45.770, 4.850),
                  ("harbor", "3", "Port", 45.780, 4.840), ("harbor", "4", "Parc", 45.790, 4.830)])
y2026 = stations([("harbor", "1", "Gare", 45.760, 4.860),            # same id
                  ("harbor", "20", "MAIRIE", 45.7701, 4.850),         # renumbered, same name
                  ("harbor", "44", "Jardin", 45.7901, 4.830),         # renumbered and renamed, 11 m away
                  ("harbor", "99", "Stade", 45.900, 4.800)])          # new

matches = match_stations(y2025, y2026)
print(matches[["station_id_old", "station_id_new", "match_method", "distance_m"]].to_string(index=False))
print(id_continuity({"2025": y2025, "2026": y2026})[["n_old", "n_same_id", "n_matched_other", "n_lost", "n_new_only"]])
```

## API

::: gbfs_toolkit.stations.match

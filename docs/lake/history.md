# history: versions only when the content changes

!!! warning "Experimental"
    Part of the experimental data-lake modules (2.1.0). See the [overview](index.md).

`system_information`, `vehicle_types`, `system_pricing_plans`, `system_regions` and
`station_information` change a few times a year, yet a collector fetches them every day. Overwriting
them loses the past; keeping every fetch repeats the same rows hundreds of times. `record_version`
keeps **one file per distinct content**, named after the UTC day of the fetch:

```text
metadata/harbor/vehicle_types/2026-01-14.parquet      the content as of 14 January
metadata/harbor/vehicle_types/2026-06-02.parquet      it changed on 2 June
```

Two fetches have the same content when their rows are equal **ignoring** the fetch time, the order
of rows and of columns, the order of keys inside a JSON text, `1` against `1.0`, and a column that is
absent against one that is empty. The order inside a JSON *array* does matter.

| Result `action` | Meaning |
|---|---|
| `written` | a new version, or the refreshed version of the current UTC day |
| `unchanged` | same content as the latest version: nothing written |
| `kept_closed_day` | a different version of a **closed** day exists; a closed day is never rewritten |
| `older_than_latest` | the fetch predates the latest version; nothing done |

`read_version(dir, "latest")` returns the newest; `read_version(dir, day, asof=True)` returns the
version in force on a past day, which is what an analysis of a past period needs.
`Collector.poll_metadata()` ([collect](collect.md)) does the fetching and the recording for you.

## Example

```python
import tempfile
import datetime as dt

import pandas as pd

from gbfs_toolkit.history import content_fingerprint, list_versions, read_version, record_version

def fetch(name, when):
    return pd.DataFrame({"vehicle_type_id": ["bike", "ebike"], "name": [name, "E-bike"],
                         "rules": ['{"a": 1, "b": 2}', "[1, 2]"], "fetched_at": pd.Timestamp(when)})

folder = tempfile.mkdtemp()
today = dt.date(2026, 7, 1)
print(record_version(fetch("City bike", "2026-01-14T10:00Z"), folder, today=today).action)   # written
print(record_version(fetch("City bike", "2026-02-20T10:00Z"), folder, today=today).action)   # unchanged
print(record_version(fetch("Vélo", "2026-06-02T10:00Z"), folder, today=today).action)        # written

print(list_versions(folder)[["version_date"]])
print(read_version(folder, "2026-03-01", asof=True)["name"].tolist())         # the January version

a = fetch("x", "2026-01-01T00:00Z")
b = a.iloc[::-1].assign(rules=["[1, 2]", '{"b": 2, "a": 1}'], fetched_at=pd.Timestamp("2027-01-01T00:00Z"))
assert content_fingerprint(a) == content_fingerprint(b)    # order and key order do not count
```

## API

::: gbfs_toolkit.history

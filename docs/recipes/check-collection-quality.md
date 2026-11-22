# Check the quality of a collection

*Which days can I trust, which not, and why?* `assess` answers per system and UTC day with one of four
statuses (`ok`, `partial`, `outage_collector`, `outage_operator`) and an incident registry. It reads a
lake, a folder of day files or a frame, and a folder is read **in place**, so a month of Paris is no
harder than a day.

```python
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from gbfs_toolkit.quality import STATUSES, assess, write_incidents
from gbfs_toolkit.store import write_lake

# A collection of two systems over three days. Everything stops for 5 hours on the 2nd (the
# collector was down); "lakeside" also loses its feed on the 3rd (the operator).
rng = np.random.default_rng(0)
frames = []
for system in ("riverside", "lakeside"):
    t = pd.date_range("2026-03-01", periods=3 * 1440, freq="min", tz="UTC")
    t = t[(t < "2026-03-02T02:00Z") | (t >= "2026-03-02T07:00Z")]
    if system == "lakeside":
        t = t[t < "2026-03-03T00:00Z"]
    frames.append(pd.DataFrame({
        "system_id": system, "station_id": "s1", "observed_at_utc": t,
        "num_bikes_available": rng.integers(0, 12, len(t)),
        "num_docks_available": rng.integers(0, 12, len(t)),
    }))
lake = Path(tempfile.mkdtemp()) / "lake"
write_lake(pd.concat(frames, ignore_index=True), lake)

# 1. Assess the folder itself (nothing is loaded whole). Leave today out in real use: pass
#    end="<yesterday>", since a day still being collected is "partial".
report = assess(lake, time_col="observed_at_utc", end="2026-03-03")
print(report.coverage[["date_utc", "system_id", "completeness_pct", "status"]].to_string(index=False))

# 2. What happened? The gap and the silent feed were found and given stable identifiers.
print(report.incidents[["incident_id", "cause", "scope"]].to_string(index=False))
print(report.summary()["days_by_status"])

# 3. A gate for a script: the days you accept, and the days you must look at.
bad = report.coverage[report.coverage["status"] != "ok"]
print(f"{len(bad)} system-day(s) to look at")
assert set(report.coverage["status"]) <= set(STATUSES)

# 4. Keep the registry next to the data; add what only you know (a migration, a known fault).
write_incidents(report.incidents, lake.parent / "incidents.json")
```

Reading the statuses: `ok` is at least 95 % of the expected polls (`ok_threshold_pct`); `outage_collector`
is a day that overlaps a stretch in which **no** system was polled (the collection's fault, not the
operators'); `outage_operator` is a day with nothing from this system while others were collected;
`partial` is anything else, with no explanation. The expected number of polls is one a minute
(`poll_resolution="15min"` for 96 a day, or `expected_polls=`).

From a shell: `gbfs quality data/lake --end 2026-03-31 --strict` exits `1` if any system-day is not `ok`
([command line](../lake/cli.md)). The same works on a collection folder (`data/collected`).

The three row-level indicators (`add_quality_indicators`) flag values that are ambiguous at the source
(`both_zero_suspect`, a field an operator never publishes, a poll in which everything reads zero). They
**flag and never remove**: what to do with a flagged row is your analysis's decision. They return a row per
input row, so they take a frame: read the part you need with `read_lake`.

See also [quality](../lake/quality.md) for every definition.

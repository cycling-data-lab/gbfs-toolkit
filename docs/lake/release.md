# release: freezing a period

!!! warning "Experimental"
    Part of the experimental data-lake modules (2.1.0). See the [overview](index.md).

`freeze_release` turns a **closed** UTC period of a [lake](store.md) into a new folder:

```text
data/<table>/system_id=<id>/year=2026/month=03/data.parquet    cut at the period's bounds
daily_coverage.csv, daily_coverage.parquet                      polls expected and obtained per day
incidents.csv, incidents.json                                   the registry for the period
data_manifest.json                                              rows and content fingerprint
datapackage.json                                                Frictionless Data Package
croissant.json                                                  Croissant metadata (optional)
README.md                                                       what is in it, coverage, incidents, licence
SHA256SUMS                                                      one checksum per file
```

It **uploads nothing and registers nothing**. Depositing the folder (Zenodo, Dataverse, a bucket) is
yours to do, and so is the choice of licence: there is no default. Without `license=` the README says
the release has no licence declared. `producers=` lists who published the original feeds, to credit.

It refuses a period that is not over (`allow_open_period=True` overrides it) and a destination that
is not empty: a release is written once.

The coverage and the incidents are computed from the released rows with [quality](quality.md), so
the README states honestly which days are complete. The Croissant file is a minimal description
(record set, fields, the Parquet file set); validate it with the MLCommons tools before relying on it.

## Verifying

`verify_release(folder)` checks every file against `SHA256SUMS` (the file `sha256sum -c` reads) and
refuses unlisted files; `deep=True` also reads the table back and compares it with
`data_manifest.json` (rows and [content fingerprint](repro.md)), which catches a file that was
re-encoded and re-checksummed.

## Example

```python
import tempfile
from pathlib import Path

import pandas as pd

from gbfs_toolkit.release import freeze_release, verify_release
from gbfs_toolkit.store import write_lake

t = pd.date_range("2026-03-01", periods=2 * 1440, freq="min", tz="UTC")
snapshots = pd.concat([
    pd.DataFrame({"system_id": "alpha", "station_id": "s1", "observed_at_utc": t,
                  "num_bikes_available": 3, "num_docks_available": 5}),
    pd.DataFrame({"system_id": "beta", "station_id": "s1", "observed_at_utc": t[:1440],
                  "num_bikes_available": 3, "num_docks_available": 5}),     # silent on the 2nd
])
work = Path(tempfile.mkdtemp())
write_lake(snapshots, work / "lake")

info = freeze_release(
    work / "lake", work / "release", name="demo-2026-03",
    start="2026-03-01", end="2026-03-02", license="CC-BY-4.0",
    producers=[{"system_id": "alpha", "producer": "City of Alpha", "license": "Open licence 2.0"}],
    incidents=[{"incident_id": "migration", "start_utc": "2026-03-01T00:00Z", "end_utc": "2026-03-01T06:00Z",
                "scope": "alpha", "cause": "ambiguous_missing_value", "summary": "Counts were written as 0 when missing."}],
)
print(info["rows"], info["systems"], info["files"])
print(sorted(p.name for p in (work / "release").iterdir()))
print((work / "release" / "README.md").read_text()[:900])

print(verify_release(work / "release", deep=True))
(work / "release" / "README.md").write_text("edited after the fact")
print(verify_release(work / "release", strict=False)["mismatched"])
```

## API

::: gbfs_toolkit.release

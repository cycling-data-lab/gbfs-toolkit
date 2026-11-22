# Freeze a version for Zenodo

*I have a closed period of a lake and I want a folder someone else can check.* `freeze_release` cuts the
data at the period, adds the daily coverage and incidents, a Frictionless `datapackage.json`, a Croissant
file, a README and a `SHA256SUMS`. It **uploads nothing** and has **no default licence**: the licence is
yours to choose, and the data are probably not only yours (a feed has its own terms).

```python
import tempfile
from pathlib import Path

import pandas as pd

from gbfs_toolkit.release import freeze_release, verify_release
from gbfs_toolkit.repro import fingerprint
from gbfs_toolkit.store import write_lake

# A lake with two days of one system (synthetic).
t = pd.date_range("2026-03-01", periods=2 * 1440, freq="min", tz="UTC")
snapshots = pd.DataFrame({"system_id": "alpha", "station_id": "s1", "observed_at_utc": t,
                          "num_bikes_available": 3, "num_docks_available": 5})
work = Path(tempfile.mkdtemp())
write_lake(snapshots, work / "lake")

# 1. Freeze the closed period (the end must be in the past). State the licences you know.
info = freeze_release(
    work / "lake", work / "release", name="alpha-2026-03",
    start="2026-03-01", end="2026-03-02", license="CC-BY-4.0",
    title="Alpha bike share, station status, March 2026",
    producers=[{"system_id": "alpha", "producer": "City of Alpha", "license": "Open licence 2.0"}],
)
print(info["rows"], info["systems"], info["files"])
print(sorted(p.name for p in (work / "release").iterdir()))

# 2. Verify it as the person who downloads it would: every file against SHA256SUMS ...
print(verify_release(work / "release")["ok"])
# ... and the content (rows and fingerprint) against the manifest, which also catches a file that
# was re-encoded and re-checksummed.
print(verify_release(work / "release", deep=True)["ok"])

# 3. The fingerprint depends on the content, not on file layout or row order.
print(fingerprint(work / "release" / "data" / "station_status"))
```

Then, outside the library:

1. read the generated `README.md` (it says what is and is not in the folder, and that there is no licence if
   you gave none);
2. deposit the **folder** on Zenodo (or any repository) yourself;
3. add the DOI Zenodo gives to your `CITATION.cff`, and keep the release's name and version in the
   paper's data statement.

From a shell: `gbfs release data/lake releases/alpha-2026-03 --name alpha-2026-03 --start 2026-03-01
--end 2026-03-31 --license CC-BY-4.0` and `gbfs verify releases/alpha-2026-03 --deep`. A release is
written once: the folder must not exist or must be empty. See [release](../lake/release.md) and
[repro](../lake/repro.md).

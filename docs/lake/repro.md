# repro: manifest and fingerprint

!!! warning "Experimental"
    Part of the experimental data-lake modules (2.1.0). See the [overview](index.md).

An analysis that cites "the stations of one city in March" is reproducible only if someone can check that
the table they rebuilt is the table the authors used. `gbfs_toolkit.repro` provides the pieces.

## The fingerprint

`fingerprint(table)` is a SHA-256 of a table's **content**. It does not depend on the order of the
rows, on the file format, or on the tool that wrote the file:

- columns are taken by name (sorted), and the names are part of the hash, so renaming a column changes it;
- numbers are written with 12 significant digits, so `1` and `1.0`, or a float that went through another
  tool, agree. **Differences beyond the 12th digit are not detected, by design;**
- times are microseconds since 1970 UTC; booleans `0` and `1`; an empty value `∅`;
- each row is hashed (MD5), the hashes are sorted, and the names plus the hashes are hashed again.

The same value can be computed in DuckDB, for a table `t`:

```sql
SELECT 'sha256:' || sha256('col_a|col_b' || chr(10) || coalesce(string_agg(h, '' ORDER BY h), ''))
FROM (SELECT md5(concat_ws('|',
        coalesce(CAST(epoch_us(CAST("col_a" AS TIMESTAMPTZ)) AS VARCHAR), '∅'),
        coalesce(printf('%.12g', CASE WHEN isnan(CAST("col_b" AS DOUBLE)) THEN NULL
                                       ELSE CAST("col_b" AS DOUBLE) END), '∅'))) AS h
      FROM t);
```

(columns in alphabetical order, one `coalesce` expression per column by type; the test suite checks
that this agrees with `fingerprint`.)

## The manifest

`create_manifest` records the table name, how it was selected (systems, UTC days, columns), the number
of rows and the fingerprint in a small JSON file. Nothing in it depends on a machine or a user.
`verify_manifest` compares data with it; `materialize` reads the selection again from a
[lake](store.md) (or a [release](release.md)'s `data/<table>` folder, or your own `reader`), verifies it,
and keeps a Parquet copy in a cache folder that git ignores. `export_sample` writes a few stations of a
table, a few megabytes, as a lake plus a manifest of its own, for a CI run that cannot hold the real data
(point your code at the sample folder in CI, at the real lake elsewhere).

## Example

```python
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from gbfs_toolkit.repro import (
    create_manifest, export_sample, fingerprint, materialize, verify_manifest, write_manifest)
from gbfs_toolkit.store import write_lake

rng = np.random.default_rng(2)
t = pd.date_range("2026-03-01", periods=3 * 288, freq="5min", tz="UTC")
table = pd.DataFrame({
    "system_id": "harbor", "station_id": [f"s{i % 12}" for i in range(len(t))], "observed_at_utc": t,
    "num_bikes_available": rng.integers(0, 15, len(t)),
})
work = Path(tempfile.mkdtemp())
write_lake(table, work / "lake")

# What the analysis used: March 1st, as a manifest.
used = table[table.observed_at_utc < "2026-03-02"]
manifest = create_manifest(used, table="station_status", systems=["harbor"], start="2026-03-01", end="2026-03-01")
write_manifest(manifest, work / "data_manifest.json")

# Somebody else rebuilds it from the lake, in another row order, and checks it.
path = materialize(manifest, work / "lake", cache_dir=work / "cache")
print(verify_manifest(manifest, pd.read_parquet(path).sample(frac=1, random_state=0)))
print(fingerprint(used) == fingerprint(used.iloc[::-1]))

# A small copy for continuous integration.
sample = export_sample(table, work / "sample", table="station_status", stations=3)
print(sample["stations"], sample["rows"])
```

## API

::: gbfs_toolkit.repro

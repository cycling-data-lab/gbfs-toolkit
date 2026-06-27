# Data model

The canonical data model is the central technical contract of `gbfs-toolkit`. Ingestion is
normalised once into version-independent pandas frames, and every audit and analysis function
operates purely on those frames. Downstream code depends on these column names and dtypes, never
on the raw GBFS JSON, so a study written against the model keeps working across GBFS 1.x, 2.x and
3.x and across feed-provider quirks.

The schema definitions live in `gbfs_toolkit.models.SCHEMAS`. The full, authoritative column
lists are rendered in the [API reference](api.md#canonical-data-model). This page states the
contract and the guarantees a researcher needs before performing joins or merges.

## Dtype guarantees

Two guarantees matter for correctness and reproducibility.

### Timestamps are timezone-aware UTC

`last_reported` and `fetched_at` are `datetime64[ns, UTC]`. GBFS 2.x unix seconds and GBFS 3.x
RFC-3339 strings are both parsed to this single dtype, so snapshots from different cities and feed
versions merge unambiguously. Convert to local time explicitly, for example with
`build_availability_panel(target_tz=...)`, before any daily or diurnal aggregation. Otherwise the
day boundary falls at UTC midnight, which is mid-afternoon in the Americas and silently corrupts
diurnal analysis.

### Missing values are never silently zero

Counts use the nullable `Int64` extension dtype, boolean flags use `boolean`, and identifiers and
names use `string`. A field absent from an older feed version is `pd.NA`, never `0` or `False`.
This survives the outer join in `join_availability`: a station present in only one endpoint keeps
`pd.NA` rather than being upcast to `float64`, which would corrupt equality tests and boolean
logic on orphaned stations.

### Why extension dtypes rather than the classic ones

The canonical schema uses pandas extension dtypes deliberately. The classic dtypes silently corrupt
data in exactly the situations a multi-city, multi-version study runs into.

| Field kind | Classic dtype and its failure | Canonical dtype | Guarantee |
|---|---|---|---|
| Counts | `float64` after a join inserts `NaN`, so `== 0` checks and integer arithmetic break | `Int64` | Missing stays `pd.NA`; counts remain integers |
| Flags | `object` or `float64` makes `if flag` ambiguous when the value is missing | `boolean` | Three-valued logic; `pd.NA` is distinct from `False` |
| Identifiers and names | `object` mixes strings and floats after a merge | `string` | A single, consistent text dtype |
| Timestamps | naive `datetime64[ns]` aligns cities at the wrong instant | `datetime64[ns, UTC]` | Unambiguous cross-city and cross-version merges |

## The four canonical frames

### StationInfo

Static description of each docking station.

| Column | Dtype | Meaning |
|---|---|---|
| `system_id` | `string` | System identifier, stable across endpoints |
| `station_id` | `string` | Station identifier within the system |
| `name` | `string` | Human-readable station name |
| `lat`, `lon` | `float64` | Coordinates in EPSG:4326 |
| `capacity` | `Int64` | Declared docking capacity |
| `station_type` | `string` | `physical`, `virtual` or `free_floating` |
| `is_virtual_station` | `boolean` | Virtual station marker |

### StationStatus

Time-varying availability for each station.

| Column | Dtype | Meaning |
|---|---|---|
| `system_id`, `station_id` | `string` | Join keys onto StationInfo |
| `num_bikes_available` | `Int64` | Rentable vehicles at the station |
| `num_docks_available` | `Int64` | Free docks at the station |
| `is_renting`, `is_returning`, `is_installed` | `boolean` | Operational flags |
| `last_reported` | `datetime64[ns, UTC]` | Operator-reported observation time |
| `fetched_at` | `datetime64[ns, UTC]` | Time the snapshot was collected |
| `gbfs_version` | `string` | Source feed version |

### VehicleStatus

Individual free-floating or dockable vehicles.

| Column | Dtype | Meaning |
|---|---|---|
| `system_id`, `vehicle_id` | `string` | Vehicle identity |
| `vehicle_type_id` | `string` | Resolves to pedal, e-bike or scooter |
| `lat`, `lon` | `float64` | Vehicle position in EPSG:4326 |
| `is_reserved`, `is_disabled` | `boolean` | Availability flags |
| `station_id` | `string` | Set when parked at a station, else `pd.NA` for free-floating |
| `current_range_meters`, `current_fuel_percent` | `Int64`, `float64` | Battery and range fields |
| `pricing_plan_id` | `string` | Preserved for cost and equity joins |
| `fetched_at` | `datetime64[ns, UTC]` | Collection time |
| `gbfs_version` | `string` | Source feed version |

### AuditVerdict

One row per station, returned by `audit_static`.

| Column | Dtype | Meaning |
|---|---|---|
| `system_id`, `station_id` | `string` | Identity of the audited station |
| `A1` to `A7` | `boolean` | Per-rule flags, see [Methodology](methodology.md) |
| `flagged` | `boolean` | True if any rule fired |
| `reason` | `string` | Human-readable explanation of the verdict |

## Validating and coercing a frame

A frame read back from a Parquet lake, or one produced by external code, can be checked or
repaired against the contract before use:

```python
import gbfs_toolkit as gb
from gbfs_toolkit.models import SCHEMAS

gb.validate_schema(df, SCHEMAS["station_status"])   # raises SchemaError on mismatch
df = gb.coerce_schema(df, SCHEMAS["station_status"]) # cast to the canonical dtypes
```

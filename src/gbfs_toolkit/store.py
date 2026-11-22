"""A Parquet lake partitioned by system, year and month, with common column names.

!!! warning "Experimental"
    Part of the experimental data-lake modules added in 2.1.0: names, parameters and output
    columns may change in a minor release (see the API policy).

The layout is plain Hive partitioning, which DuckDB, Arrow, Spark and pandas all read without
this library::

    <root>/system_id=<id>/year=2026/month=03/data.parquet

`harmonize` gives station and vehicle snapshots the same column names whatever collected
them (``observed_at_utc``, ``system_id``, ``station_id`` ...), keeps time in UTC and, when you
give the system's IANA time zone, adds the local wall clock and the UTC offset.
`write_lake` writes a frame into the lake (never half-written files) and
`read_lake` reads a system and a time window back, filtering on the partitions before it
loads anything. `register_duckdb_views` exposes lakes as DuckDB views (extra ``duckdb``).

Parquet needs ``pip install gbfs-toolkit[parquet]``; the views need
``pip install gbfs-toolkit[duckdb]``.

Examples
--------
>>> import tempfile, pandas as pd
>>> from gbfs_toolkit.store import harmonize, write_lake, read_lake
>>> raw = pd.DataFrame({
...     "system_id": "demo", "station_id": ["s1", "s2"],
...     "fetched_at": pd.to_datetime(["2026-03-01T10:00Z"] * 2),
...     "num_bikes_available": [3, 0], "num_docks_available": [7, 10]})
>>> tidy = harmonize(raw, tz="Europe/Paris")
>>> int(tidy.loc[0, "utc_offset_min"])
60
>>> with tempfile.TemporaryDirectory() as lake:
...     _ = write_lake(tidy, lake)
...     back = read_lake(lake, systems=["demo"])
>>> len(back), sorted(back["station_id"])
(2, ['s1', 's2'])
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from gbfs_toolkit.core._common import atomic_write, need_columns, require_pyarrow, to_utc
from gbfs_toolkit.core.errors import GBFSValidationError

__all__ = [
    "LAKE_FORMAT",
    "LAKE_METADATA_FILE",
    "STATION_STATUS_FIELDS",
    "harmonize",
    "write_lake",
    "read_lake",
    "list_partitions",
    "read_lake_metadata",
    "duckdb_view_sql",
    "register_duckdb_views",
]

_log = logging.getLogger(__name__)

LAKE_FORMAT = "gbfs-toolkit-lake/1"
LAKE_METADATA_FILE = "lake.json"
#: Leading columns of a harmonised station-status frame (the rest follow, unchanged).
STATION_STATUS_FIELDS: list[str] = [
    "observed_at_utc",
    "observed_at_local",
    "utc_offset_min",
    "system_id",
    "station_id",
    "num_bikes_available",
    "num_docks_available",
    "is_renting",
    "is_returning",
    "last_reported_utc",
]
_RENAMES = {"fetched_at": "observed_at_utc", "last_reported": "last_reported_utc"}
_COUNTS = ("num_bikes_available", "num_docks_available")
_FLAGS = ("is_renting", "is_returning", "is_installed", "is_disabled", "is_reserved")
_PARTITIONS = ("system_id", "year", "month")


def _zone_of(tz: str | Mapping[str, str] | None, system: str) -> str | None:
    if tz is None:
        return None
    return tz if isinstance(tz, str) else tz.get(system)


def harmonize(
    df: pd.DataFrame,
    kind: str = "station_status",
    *,
    system_id: str | None = None,
    tz: str | Mapping[str, str] | None = None,
) -> pd.DataFrame:
    """Common names and types for snapshots, with UTC time and, optionally, local time.

    ``fetched_at`` becomes ``observed_at_utc`` and ``last_reported`` ``last_reported_utc``, both
    tz-aware UTC; counts are nullable integers and flags nullable booleans, so a value the feed
    left out stays empty. ``system_id`` is filled from the argument when the frame lacks it.
    With ``tz`` (an IANA zone, or ``{system_id: zone}``) the frame gains ``observed_at_local``
    (the wall clock, no zone attached) and ``utc_offset_min``.

    Parameters
    ----------
    kind : {"station_status", "vehicle_status"}
        Which fields lead the result; the other columns follow unchanged.

    Raises
    ------
    ValueError
        For an unknown ``kind`` or a time zone that does not exist.

    Examples
    --------
    >>> import pandas as pd
    >>> raw = pd.DataFrame({"station_id": ["s"], "fetched_at": ["2026-07-01T10:00:00Z"],
    ...                     "num_bikes_available": [2]})
    >>> out = harmonize(raw, system_id="demo", tz="Europe/Paris")
    >>> out.loc[0, "observed_at_local"].hour, int(out.loc[0, "utc_offset_min"])
    (12, 120)
    """
    if kind not in ("station_status", "vehicle_status"):
        raise ValueError(f"kind must be 'station_status' or 'vehicle_status', got {kind!r}")
    out = df.rename(columns={k: v for k, v in _RENAMES.items() if k in df.columns}).copy()
    if "observed_at_utc" not in out.columns:
        need_columns(out, ["fetched_at"], what="harmonize")
    if "system_id" not in out.columns:
        if system_id is None:
            need_columns(out, ["system_id"], what="harmonize (or pass system_id=)")
        out["system_id"] = system_id
    out["system_id"] = out["system_id"].astype("string")
    out["observed_at_utc"] = to_utc(out["observed_at_utc"], what="observed_at_utc").to_numpy()
    if "last_reported_utc" in out.columns:
        out["last_reported_utc"] = pd.to_datetime(
            out["last_reported_utc"], utc=True, errors="coerce"
        )
    for c in _COUNTS:
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce").astype("Int64")
    for c in _FLAGS:
        if c in out.columns:
            out[c] = out[c].astype("boolean")
    for c in ("station_id", "vehicle_id"):
        if c in out.columns:
            out[c] = out[c].astype("string")
    if tz is not None:
        local, offset = [], []
        for obs, system in zip(out["observed_at_utc"], out["system_id"], strict=True):
            zone = _zone_of(tz, str(system))
            if zone is None:
                local.append(pd.NaT)
                offset.append(pd.NA)
                continue
            here = obs.tz_convert(zone)
            local.append(here.tz_localize(None))
            offset.append(int(here.utcoffset().total_seconds() // 60))
        out["observed_at_local"] = pd.to_datetime(local)
        out["utc_offset_min"] = pd.array(offset, dtype="Int16")
    lead = [c for c in STATION_STATUS_FIELDS if c in out.columns]
    return out[lead + [c for c in out.columns if c not in lead]]


def _time_column(df: pd.DataFrame, time_col: str | None) -> str:
    if time_col is not None:
        need_columns(df, [time_col], what="write_lake")
        return time_col
    for c in ("observed_at_utc", "fetched_at"):
        if c in df.columns:
            return c
    need_columns(df, ["observed_at_utc"], what="write_lake (or pass time_col=)")
    raise AssertionError  # unreachable


def _partition_dir(root: Path, system: str, year: int, month: int) -> Path:
    if not system or "/" in system or "\\" in system or system.startswith("."):
        raise ValueError(f"system_id {system!r} cannot be used as a folder name")
    return root / f"system_id={system}" / f"year={year:04d}" / f"month={month:02d}"


def write_lake(
    df: pd.DataFrame,
    root: str | Path,
    *,
    mode: str = "append",
    time_col: str | None = None,
    timezones: Mapping[str, str] | None = None,
    compression: str = "zstd",
) -> pd.DataFrame:
    """Write ``df`` into the lake under ``root``, one partition per (system, UTC year, UTC month).

    ``mode`` says what happens to a partition that already holds data:

    ``"append"`` (default)
        a new file ``part-<id>.parquet`` is added next to the others: nothing is lost, and
        concurrent writers never touch the same file. Duplicates are not removed;
    ``"merge"``
        the partition's files and the new rows are combined, exact duplicate rows are
        dropped, and one ``data.parquet`` replaces them;
    ``"replace"``
        the partition holds only the new rows.

    The system is the folder name and is not repeated inside the files (a reader of the lake
    gets it back as the ``system_id`` column). Every file is written to a temporary name and renamed, so a reader never sees a half
    file. ``timezones`` (``{system_id: zone}``) is recorded in ``lake.json``. The time column
    defaults to ``observed_at_utc`` (then ``fetched_at``); it must be tz-aware or UTC-naive.

    Returns
    -------
    pandas.DataFrame
        One row per touched partition: ``system_id, year, month, rows, path``.

    Examples
    --------
    >>> import tempfile, pandas as pd
    >>> df = pd.DataFrame({"system_id": "a", "station_id": "s",
    ...                    "observed_at_utc": pd.to_datetime(["2026-01-31T23:59Z", "2026-02-01T00:01Z"])})
    >>> with tempfile.TemporaryDirectory() as lake:
    ...     touched = write_lake(df, lake)
    >>> touched[["year", "month", "rows"]].values.tolist()
    [[2026, 1, 1], [2026, 2, 1]]
    """
    if mode not in ("append", "merge", "replace"):
        raise ValueError(f"mode must be 'append', 'merge' or 'replace', got {mode!r}")
    require_pyarrow("write_lake")
    need_columns(df, ["system_id"], what="write_lake")
    tcol = _time_column(df, time_col)
    root_path = Path(root)
    times = to_utc(df[tcol], what=tcol)
    work = df.copy()
    work[tcol] = times.to_numpy()
    system = work["system_id"].astype(str)
    year, month = times.dt.year.to_numpy(), times.dt.month.to_numpy()
    summary: list[dict[str, Any]] = []
    for (sys_id, y, m), idx in (
        pd.DataFrame({"s": system.to_numpy(), "y": year, "m": month})
        .groupby(["s", "y", "m"], sort=True)
        .groups.items()
    ):
        part = work.iloc[np.asarray(idx)].drop(columns=["system_id"])
        folder = _partition_dir(root_path, str(sys_id), int(y), int(m))
        if mode == "append":
            target = folder / f"part-{uuid.uuid4().hex}.parquet"
        else:
            target = folder / "data.parquet"
        combined = part
        stale: list[Path] = []
        if mode == "merge" and folder.is_dir():
            stale = sorted(folder.glob("*.parquet"))
            frames = [pd.read_parquet(f) for f in stale]
            combined = pd.concat([*frames, part], ignore_index=True).drop_duplicates()
        if mode == "replace" and folder.is_dir():
            stale = [f for f in folder.glob("*.parquet") if f != target]
        flat = combined.reset_index(drop=True)

        def write(tmp: Path, frame: pd.DataFrame = flat) -> None:
            frame.to_parquet(tmp, index=False, compression=compression)

        atomic_write(target, write)
        for old in stale:
            if old != target:
                old.unlink(missing_ok=True)
        summary.append(
            {
                "system_id": str(sys_id),
                "year": int(y),
                "month": int(m),
                "rows": int(len(part)),
                "path": str(target.relative_to(root_path)),
            }
        )
    _update_metadata(root_path, tcol, timezones)
    _log.info("lake %s: %d row(s) in %d partition(s) (%s)", root_path, len(df), len(summary), mode)
    return pd.DataFrame(summary, columns=["system_id", "year", "month", "rows", "path"])


def _update_metadata(root: Path, tcol: str, timezones: Mapping[str, str] | None) -> None:
    path = root / LAKE_METADATA_FILE
    meta: dict[str, Any] = {}
    if path.exists():
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            _log.warning("%s is not valid JSON; rewriting it", path)
    meta.update({"format": LAKE_FORMAT, "partitioning": list(_PARTITIONS), "time_column": tcol})
    zones = dict(meta.get("timezones", {}))
    zones.update(timezones or {})
    if zones:
        meta["timezones"] = dict(sorted(zones.items()))
    atomic_write(
        path, lambda tmp: tmp.write_text(json.dumps(meta, indent=1) + "\n", encoding="utf-8")
    )


def read_lake_metadata(root: str | Path) -> dict[str, Any]:
    """The lake's ``lake.json`` (format, partitioning, time column, time zones); ``{}`` if absent."""
    path = Path(root) / LAKE_METADATA_FILE
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _partitioning() -> Any:
    import pyarrow as pa
    import pyarrow.dataset as ds

    schema = pa.schema([("system_id", pa.string()), ("year", pa.int32()), ("month", pa.int32())])
    return ds.partitioning(schema, flavor="hive")


def list_partitions(root: str | Path) -> pd.DataFrame:
    """The partitions present under ``root``: ``system_id, year, month, files, bytes``."""
    base = Path(root)
    rows = []
    for folder in sorted(base.glob("system_id=*/year=*/month=*")):
        files = list(folder.glob("*.parquet"))
        if not files:
            continue
        rows.append(
            {
                "system_id": folder.parent.parent.name.split("=", 1)[1],
                "year": int(folder.parent.name.split("=", 1)[1]),
                "month": int(folder.name.split("=", 1)[1]),
                "files": len(files),
                "bytes": sum(f.stat().st_size for f in files),
            }
        )
    return pd.DataFrame(rows, columns=["system_id", "year", "month", "files", "bytes"])


def read_lake(
    root: str | Path,
    *,
    systems: Iterable[str] | None = None,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
    columns: list[str] | None = None,
    time_col: str | None = None,
) -> pd.DataFrame:
    """Read a lake back: ``systems`` and the window ``start <= time < end`` (UTC).

    Systems and months outside the window are skipped from the folder names, before any file
    is opened. ``columns`` limits what is loaded (the partition folders ``year`` and ``month``
    are returned only if you ask for them). An absent or empty lake returns an empty frame.

    Raises
    ------
    GBFSValidationError
        If ``root`` exists but has no recognisable partition and no readable file.

    Examples
    --------
    >>> import tempfile, pandas as pd
    >>> df = pd.DataFrame({"system_id": ["a", "b"], "station_id": "s",
    ...                    "observed_at_utc": pd.to_datetime(["2026-03-01T10:00Z"] * 2)})
    >>> with tempfile.TemporaryDirectory() as lake:
    ...     _ = write_lake(df, lake)
    ...     only_b = read_lake(lake, systems=["b"])
    >>> only_b["system_id"].tolist()
    ['b']
    """
    require_pyarrow("read_lake")
    import pyarrow.dataset as ds

    base = Path(root)
    meta = read_lake_metadata(base)
    tcol = time_col or meta.get("time_column", "observed_at_utc")
    if not base.is_dir() or not any(base.glob("system_id=*/year=*/month=*/*.parquet")):
        if base.is_dir() and any(base.rglob("*.parquet")):
            raise GBFSValidationError(
                f"{base} has Parquet files but not the system_id=/year=/month= layout"
            )
        return pd.DataFrame(columns=columns or [])
    files = sorted(str(f) for f in base.glob("system_id=*/year=*/month=*/*.parquet"))
    dataset = ds.dataset(
        files, format="parquet", partitioning=_partitioning(), partition_base_dir=str(base)
    )
    expr = None

    def both(a: Any, b: Any) -> Any:
        return b if a is None else a & b

    if systems is not None:
        expr = both(expr, ds.field("system_id").isin([str(s) for s in systems]))
    lo = None if start is None else to_utc([start]).iloc[0]
    hi = None if end is None else to_utc([end]).iloc[0]
    if lo is not None:
        ym = lo.year * 100 + lo.month
        expr = both(expr, (ds.field("year") * 100 + ds.field("month")) >= ym)
    if hi is not None:
        last = hi - pd.Timedelta(1, "ns")
        ym = last.year * 100 + last.month
        expr = both(expr, (ds.field("year") * 100 + ds.field("month")) <= ym)
    wanted = columns
    if columns is not None and (lo is not None or hi is not None) and tcol not in columns:
        wanted = [*columns, tcol]
    table = dataset.to_table(columns=wanted, filter=expr)
    out = table.to_pandas()
    if (lo is not None or hi is not None) and tcol in out.columns:
        t = to_utc(out[tcol], what=tcol)
        mask = pd.Series(True, index=out.index)
        if lo is not None:
            mask &= t >= lo
        if hi is not None:
            mask &= t < hi
        out = out[mask.to_numpy()]
    if columns is not None:
        out = out[[c for c in columns if c in out.columns]]
    else:  # year and month are the time column's folders, not data
        out = out.drop(columns=[c for c in ("year", "month") if c in out.columns])
    return out.reset_index(drop=True)


_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def duckdb_view_sql(root: str | Path, name: str) -> str:
    """The ``CREATE OR REPLACE VIEW`` statement that exposes a lake to DuckDB.

    The view reads every Parquet file under ``root`` with Hive partitioning, so ``system_id``,
    ``year`` and ``month`` are columns (typed text and integers) and queries on them skip the
    folders they exclude. It needs no import of DuckDB, so it can be printed and run elsewhere.

    Examples
    --------
    >>> sql = duckdb_view_sql("/data/lake", "station_status")
    >>> sql.startswith("CREATE OR REPLACE VIEW station_status AS SELECT * FROM read_parquet(")
    True
    """
    if not _IDENT.match(name):
        raise ValueError(f"view name {name!r} is not a plain SQL identifier")
    path = str(Path(root).resolve()).replace("'", "''")
    return (
        f"CREATE OR REPLACE VIEW {name} AS SELECT * FROM read_parquet('{path}/*/*/*/*.parquet', "
        "hive_partitioning = true, union_by_name = true, "
        "hive_types = {'system_id': VARCHAR, 'year': INTEGER, 'month': INTEGER})"
    )


def register_duckdb_views(con: Any, tables: Mapping[str, str | Path]) -> list[str]:
    """Create one DuckDB view per lake: ``tables`` maps a view name to a lake folder.

    ``con`` is a ``duckdb.DuckDBPyConnection``. Returns the names created. Requires
    ``pip install gbfs-toolkit[duckdb]`` only to obtain the connection: the function just runs
    `duckdb_view_sql`.

    """
    created = []
    for name, root in tables.items():
        con.execute(duckdb_view_sql(root, name))
        created.append(name)
    return created

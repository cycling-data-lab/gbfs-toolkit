"""Station availability aggregated to 15 minutes, an hour or a day, with fixed definitions.

!!! warning "Experimental"
    Part of the experimental data-lake modules added in 2.1.0: names, parameters and output
    columns may change in a minor release (see the API policy).

Minute-level snapshots are too many to plot or to join; what an analysis usually needs is a
station-by-bucket table whose columns mean the same thing every time. `aggregate_availability`
produces one, with these definitions (they will not change silently):

``n_obs``
    rows in the bucket, all of them. Nothing is dropped or de-duplicated here, so
    **the sum of ``n_obs`` over all buckets is the number of input rows**, at every frequency
    (`check_conservation` verifies it, and `aggregate_levels` does it for you);
``n_valid``
    rows that carry a bike count and are not flagged ``both_zero_suspect`` (see
    `gbfs_toolkit.quality`): the observations every other column is computed from;
``bikes_mean``, ``bikes_min``, ``bikes_max``, ``bikes_first``, ``bikes_last``
    the bike count over the valid rows (first and last in time order);
``docks_mean``, ``docks_min``
    the same for free docks (missing when the operator does not publish them);
``pct_empty``
    share of valid rows with no bike, in %;
``pct_full``
    share of valid rows where the station is full, in %: no free dock, or, when docks are
    not published and a ``capacity`` column exists, bikes at or above the capacity;
``pct_renting``
    share of valid rows where the station is renting, in %;
``pct_both_zero``
    share of **all** rows flagged ``both_zero_suspect``, in % (counted here, excluded
    elsewhere); missing if the frame carries no such column;
``movement_volume``
    sum of the absolute changes of the bike count between two consecutive valid rows of the
    same station that are at most ``max_pair_gap`` (90 s) apart, attributed to the bucket of
    the second. It estimates how many bikes moved; a rental and a return inside one poll
    cancel out and are invisible. It is a volume of movement, not a count of trips.

Buckets are aligned on UTC. With ``tz``, the local wall-clock start of each bucket and the UTC
offset are added, so a local-time analysis can group on them without recomputing the clock change.

Examples
--------
>>> import pandas as pd
>>> from gbfs_toolkit.aggregate import aggregate_availability
>>> t = pd.date_range("2026-03-01T08:00Z", periods=30, freq="min")
>>> snaps = pd.DataFrame({
...     "system_id": "demo", "station_id": "s1", "fetched_at": t,
...     "num_bikes_available": range(30), "num_docks_available": range(30, 0, -1)})
>>> agg = aggregate_availability(snaps, "15min")
>>> agg["n_obs"].tolist(), agg["bikes_first"].tolist(), agg["bikes_last"].tolist()
([15, 15], [0, 15], [14, 29])
>>> int(agg["n_obs"].sum()) == len(snaps)
True
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

from gbfs_toolkit.core._common import fixed_timedelta, need_columns, to_utc
from gbfs_toolkit.core._tabular import (
    Table,
    open_table,
    relation_of,
    resolve_engine,
    sql_name,
)
from gbfs_toolkit.core.errors import GBFSValidationError

__all__ = [
    "AGGREGATE_COLUMNS",
    "AGGREGATE_DTYPES",
    "LEVELS",
    "aggregate_availability",
    "aggregate_levels",
    "check_conservation",
]

_log = logging.getLogger(__name__)

#: Output columns (``bucket_start_local`` and ``utc_offset_min`` only when ``tz`` is given).
AGGREGATE_COLUMNS: list[str] = [
    "system_id",
    "station_id",
    "bucket_start_utc",
    "bucket_start_local",
    "utc_offset_min",
    "n_obs",
    "n_valid",
    "bikes_mean",
    "bikes_min",
    "bikes_max",
    "bikes_first",
    "bikes_last",
    "docks_mean",
    "docks_min",
    "pct_empty",
    "pct_full",
    "pct_renting",
    "pct_both_zero",
    "movement_volume",
]

#: The logical type of each column of the result (``string``, ``int64``, ``Int64``, ``Int16``,
#: ``float64``, ``datetime64[UTC]``, ``datetime64[naive]``): the exact pandas dtype of text
#: depends on the pandas version, the kind does not.
AGGREGATE_DTYPES: dict[str, str] = {
    "system_id": "string",
    "station_id": "string",
    "bucket_start_utc": "datetime64[UTC]",
    "bucket_start_local": "datetime64[naive]",
    "utc_offset_min": "Int16",
    "n_obs": "int64",
    "n_valid": "int64",
    "bikes_mean": "float64",
    "bikes_min": "Int64",
    "bikes_max": "Int64",
    "bikes_first": "Int64",
    "bikes_last": "Int64",
    "docks_mean": "float64",
    "docks_min": "Int64",
    "pct_empty": "float64",
    "pct_full": "float64",
    "pct_renting": "float64",
    "pct_both_zero": "float64",
    "movement_volume": "Int64",
}

#: The three usual levels: name -> frequency.
LEVELS: dict[str, str] = {"15m": "15min", "1h": "1h", "1d": "1D"}

_KEYS = ["system_id", "station_id", "bucket_start_utc"]
_REQUIRED = ["system_id", "station_id", "num_bikes_available"]
_OPTIONAL = ["num_docks_available", "is_renting", "capacity", "both_zero_suspect"]
_INT_COLUMNS = (
    "bikes_min",
    "bikes_max",
    "bikes_first",
    "bikes_last",
    "docks_min",
    "movement_volume",
)


def _zone_of(tz: str | Mapping[str, str] | None, systems: pd.Series) -> pd.Series | None:
    if tz is None:
        return None
    if isinstance(tz, str):
        return pd.Series(tz, index=systems.index)
    return systems.map(lambda s: tz.get(s, "UTC"))


def _num(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(np.nan, index=df.index, dtype="float64")
    return pd.to_numeric(df[col], errors="coerce").astype("float64")


def _bucketed(
    df: pd.DataFrame,
    step: pd.Timedelta,
    gap: pd.Timedelta,
    time_col: str,
    carry: pd.DataFrame | None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Aggregate one frame (pandas engine). ``carry`` is the last row of each station before it.

    Returns the raw aggregate (floats, before the final casts) and the carry for the next
    chunk: the buckets of a chunk are whole when it starts and ends on a multiple of ``step``,
    and the only thing a pair of consecutive rows needs from before is the previous row.
    """
    t = to_utc(df[time_col], what=time_col)
    w = pd.DataFrame(
        {
            "system_id": df["system_id"].astype(str).to_numpy(),
            "station_id": df["station_id"].astype(str).to_numpy(),
            "t": t.reset_index(drop=True),
            "b": _num(df, "num_bikes_available").to_numpy(),
            "d": _num(df, "num_docks_available").to_numpy(),
        }
    )
    has_flag = "both_zero_suspect" in df.columns
    suspect = (
        df["both_zero_suspect"].fillna(False).astype(bool).to_numpy()
        if has_flag
        else np.zeros(len(df), bool)
    )
    w["suspect"] = suspect
    w["valid"] = (~suspect) & w["b"].notna().to_numpy()
    w["bucket_start_utc"] = w["t"].dt.floor(step)
    # Stable sort by time inside each station: first/last and consecutive pairs depend on it.
    w = w.assign(_pos=np.arange(len(w))).sort_values(
        ["system_id", "station_id", "t", "_pos"], kind="stable"
    )
    keep_valid = w["valid"]
    w["bv"] = w["b"].where(keep_valid)
    w["dv"] = w["d"].where(~w["suspect"])
    w["empty"] = (w["bv"] == 0).astype("float64").where(keep_valid)

    d_known = w["d"].notna()
    cap = (
        pd.Series(_num(df, "capacity").to_numpy()[w["_pos"].to_numpy()], index=w.index)
        if "capacity" in df.columns
        else pd.Series(np.nan, index=w.index)
    )
    full = pd.Series(np.nan, index=w.index)
    full = full.mask(d_known & keep_valid, (w["d"] == 0).astype("float64"))
    by_cap = (~d_known) & keep_valid & cap.notna()
    full = full.mask(by_cap, (w["b"] >= cap).astype("float64"))
    w["full"] = full
    if "is_renting" in df.columns:
        renting = pd.to_numeric(df["is_renting"].astype("Float64"), errors="coerce")
        w["renting"] = pd.Series(
            renting.astype("float64").to_numpy()[w["_pos"].to_numpy()], index=w.index
        ).where(keep_valid)
    else:
        w["renting"] = np.nan
    w["suspect_f"] = w["suspect"].astype("float64") if has_flag else np.nan

    # Consecutive pairs, with the previous chunk's last row of each station in front.
    ext = w[["system_id", "station_id", "t", "b", "valid", "_pos"]]
    if carry is not None and len(carry):
        ext = pd.concat([carry.assign(_pos=-1), ext], ignore_index=True)
        ext = ext.sort_values(["system_id", "station_id", "t", "_pos"], kind="stable")
    g = ext.groupby(["system_id", "station_id"], sort=False)
    prev_b, prev_t = g["b"].shift(1), g["t"].shift(1)
    prev_ok = g["valid"].shift(1, fill_value=False).astype(bool)
    pair = ext["valid"] & prev_ok & ((ext["t"] - prev_t) <= gap)
    ext = ext.assign(move=(ext["b"] - prev_b).abs().where(pair))
    new_carry = ext.groupby(["system_id", "station_id"], sort=False).tail(1)[
        ["system_id", "station_id", "t", "b", "valid"]
    ]
    move = ext.loc[ext["_pos"] >= 0].set_index("_pos")["move"]
    w["move"] = move.reindex(w["_pos"].to_numpy()).to_numpy()

    out = w.groupby(_KEYS, sort=True).agg(
        n_obs=("t", "size"),
        n_valid=("bv", "count"),
        bikes_mean=("bv", "mean"),
        bikes_min=("bv", "min"),
        bikes_max=("bv", "max"),
        bikes_first=("bv", "first"),
        bikes_last=("bv", "last"),
        docks_mean=("dv", "mean"),
        docks_min=("dv", "min"),
        pct_empty=("empty", "mean"),
        pct_full=("full", "mean"),
        pct_renting=("renting", "mean"),
        pct_both_zero=("suspect_f", "mean"),
        movement_volume=("move", lambda s: s.sum(min_count=1)),
    )
    return out.reset_index(), new_carry.reset_index(drop=True)


def _duckdb_aggregate(
    table: Table, step: pd.Timedelta, gap: pd.Timedelta, time_col: str
) -> pd.DataFrame:
    """The same aggregate computed by DuckDB over any source (see `_bucketed`)."""
    cols = set(table.columns())
    table.check_time(time_col)

    def number(col: str) -> str:
        if col not in cols:
            return "CAST(NULL AS DOUBLE)"
        x = f"TRY_CAST({sql_name(col)} AS DOUBLE)"
        return f"CASE WHEN isnan({x}) THEN NULL ELSE {x} END"

    suspect = (
        f"coalesce(TRY_CAST({sql_name('both_zero_suspect')} AS BOOLEAN), false)"
        if "both_zero_suspect" in cols
        else "false"
    )
    suspect_f = "CAST(suspect AS DOUBLE)" if "both_zero_suspect" in cols else "CAST(NULL AS DOUBLE)"
    renting = (
        f"TRY_CAST({sql_name('is_renting')} AS DOUBLE)"
        if "is_renting" in cols
        else "CAST(NULL AS DOUBLE)"
    )
    step_us, gap_us = int(step.value // 1000), int(gap.value // 1000)
    sql = f"""
    WITH base AS (
        SELECT CAST({sql_name("system_id")} AS VARCHAR) AS system_id,
               CAST({sql_name("station_id")} AS VARCHAR) AS station_id,
               epoch_us({sql_name(time_col)}) AS t,
               {number("num_bikes_available")} AS b,
               {number("num_docks_available")} AS d,
               {number("capacity")} AS cap,
               {renting} AS ren,
               {suspect} AS suspect,
               row_number() OVER () AS pos
        FROM src
    ),
    calc AS (
        SELECT *, (NOT suspect AND b IS NOT NULL) AS valid,
               (t // {step_us}) * {step_us} AS bucket
        FROM base WHERE t IS NOT NULL
    ),
    win AS (
        SELECT *, lag(b) OVER w AS pb, lag(t) OVER w AS pt, lag(valid) OVER w AS pv
        FROM calc
        WINDOW w AS (PARTITION BY system_id, station_id ORDER BY t, pos)
    ),
    flags AS (
        SELECT system_id, station_id, bucket, t, pos,
               CASE WHEN valid THEN b END AS bv,
               CASE WHEN NOT suspect THEN d END AS dv,
               CASE WHEN valid THEN CAST(b = 0 AS DOUBLE) END AS is_empty,
               CASE WHEN valid AND d IS NOT NULL THEN CAST(d = 0 AS DOUBLE)
                    WHEN valid AND d IS NULL AND cap IS NOT NULL THEN CAST(b >= cap AS DOUBLE)
               END AS is_full,
               CASE WHEN valid THEN ren END AS renting,
               {suspect_f} AS suspect_f,
               CASE WHEN valid AND coalesce(pv, false) AND (t - pt) <= {gap_us}
                    THEN abs(b - pb) END AS move
        FROM win
    )
    SELECT system_id, station_id, bucket,
           count(*) AS n_obs, count(bv) AS n_valid,
           avg(bv) AS bikes_mean, min(bv) AS bikes_min, max(bv) AS bikes_max,
           first(bv ORDER BY t, pos) FILTER (WHERE bv IS NOT NULL) AS bikes_first,
           last(bv ORDER BY t, pos) FILTER (WHERE bv IS NOT NULL) AS bikes_last,
           avg(dv) AS docks_mean, min(dv) AS docks_min,
           avg(is_empty) AS pct_empty, avg(is_full) AS pct_full, avg(renting) AS pct_renting,
           avg(suspect_f) AS pct_both_zero, sum(move) AS movement_volume
    FROM flags GROUP BY system_id, station_id, bucket
    ORDER BY system_id, station_id, bucket
    """
    with relation_of(table) as rel:
        out = rel.query("src", sql).df()
    out["bucket_start_utc"] = pd.to_datetime(out.pop("bucket"), unit="us", utc=True)
    first = ["system_id", "station_id", "bucket_start_utc"]
    return out[first + [c for c in out.columns if c not in first]]


def _chunked_aggregate(
    table: Table, step: pd.Timedelta, gap: pd.Timedelta, time_col: str, chunk: pd.Timedelta
) -> pd.DataFrame:
    """Aggregate window by window (pandas engine, memory bounded by one window)."""
    table.check_time(time_col)
    cols = [c for c in [*_REQUIRED, time_col, *_OPTIONAL] if c in set(table.columns())]
    span = table.time_range(time_col)
    parts: list[pd.DataFrame] = []
    if span is not None:
        width = step * max(1, int(np.ceil(chunk / step)))  # a multiple of step: whole buckets
        lo = pd.Timestamp((span[0].value // width.value) * width.value, tz="UTC")
        carry: pd.DataFrame | None = None
        while lo <= span[1]:
            frame = table.window(cols, time_col, lo, lo + width)
            if len(frame):
                part, carry = _bucketed(frame, step, gap, time_col, carry)
                parts.append(part)
            lo = lo + width
    if not parts:  # no row: the empty result, with its columns
        empty = pd.DataFrame({c: pd.Series(dtype="object") for c in cols})
        empty[time_col] = pd.to_datetime(empty[time_col], utc=True)
        return _bucketed(empty, step, gap, time_col, None)[0]
    out = pd.concat(parts, ignore_index=True)
    return out.sort_values(_KEYS, kind="stable").reset_index(drop=True)


def aggregate_availability(
    df: Any,
    freq: str = "15min",
    *,
    tz: str | Mapping[str, str] | None = None,
    max_pair_gap: str | pd.Timedelta = "90s",
    time_col: str = "fetched_at",
    engine: str = "auto",
    chunk: str | pd.Timedelta = "1D",
) -> pd.DataFrame:
    """Aggregate station-status rows to buckets of ``freq`` (see the module for the definitions).

    Parameters
    ----------
    df : pandas.DataFrame, pyarrow.Table, duckdb relation, str or Path
        One row per station per poll: ``system_id``, ``station_id``, ``time_col`` and
        ``num_bikes_available``; optionally ``num_docks_available``, ``is_renting``,
        ``capacity`` and ``both_zero_suspect``. Duplicated rows are counted; de-duplicate
        first if your source can repeat a poll. Besides a pandas frame, an Arrow table or
        dataset, a DuckDB relation or a path (a lake written by `gbfs_toolkit.store`, a
        folder of Parquet files, a file or a glob) is read without loading it whole; the time
        column of those must be a timestamp.
    freq : str, default "15min"
        A fixed-width frequency: ``"15min"``, ``"1h"``, ``"1D"`` or any other.
    tz : str or mapping, optional
        An IANA zone, or ``{system_id: zone}``, for the local columns.
    max_pair_gap : str or Timedelta, default "90s"
        Longest time between two rows still counted as consecutive for ``movement_volume``.
    engine : {"auto", "duckdb", "pandas"}, default "auto"
        Who computes. A pandas frame stays on pandas under ``"auto"``; any other source goes
        to DuckDB when the ``duckdb`` extra is installed and is otherwise processed window by
        window in pandas (``chunk`` wide), so the memory used is one window, not the table.
        The engines agree: counts and integer columns are identical and the other columns
        differ by floating-point rounding at most (``n_obs`` is conserved by each). Rows with
        the same station and the same time are ordered as the source lists them.
    chunk : str or Timedelta, default "1D"
        Width of a window of the pandas engine on a table, an Arrow dataset or a path (rounded
        up to a multiple of ``freq``, so that no bucket is split).

    Returns
    -------
    pandas.DataFrame
        One row per (system, station, bucket) that has at least one row, sorted; columns as in
        `AGGREGATE_COLUMNS`.

    Raises
    ------
    ValueError
        For a calendar frequency (``"1ME"``), an unparseable time, an unknown ``engine`` or,
        for a table, a time column that is not a timestamp.

    Examples
    --------
    >>> import pandas as pd
    >>> t = pd.to_datetime(["2026-03-01T08:00Z", "2026-03-01T08:01Z", "2026-03-01T08:02Z"])
    >>> df = pd.DataFrame({"system_id": "a", "station_id": "s", "fetched_at": t,
    ...                    "num_bikes_available": [5, 3, 4]})
    >>> row = aggregate_availability(df, "1h").iloc[0]
    >>> int(row["n_obs"]), float(row["bikes_mean"]), int(row["movement_volume"])
    (3, 4.0, 3)
    """
    table = open_table(df, what="aggregate_availability")
    need_columns(
        pd.DataFrame(columns=table.columns()),
        [*_REQUIRED[:2], time_col, _REQUIRED[2]],
        what="aggregate_availability",
    )
    step = fixed_timedelta(freq, what="freq")
    gap = fixed_timedelta(max_pair_gap, what="max_pair_gap")
    window = fixed_timedelta(chunk, what="chunk")
    use = resolve_engine(engine, table, what="aggregate_availability")
    if use == "duckdb":
        out = _duckdb_aggregate(table, step, gap, time_col)
    elif table.kind == "pandas":
        out = _bucketed(table.df, step, gap, time_col, None)[0]  # type: ignore[attr-defined]
    else:
        out = _chunked_aggregate(table, step, gap, time_col, window)
    out = _finish(out, tz)
    _log.info("aggregate: %d rows -> %d buckets of %s (%s)", table.count(), len(out), freq, use)
    return out


def _finish(out: pd.DataFrame, tz: str | Mapping[str, str] | None) -> pd.DataFrame:
    """The casts, the local columns and the column order shared by every engine."""
    out = out.copy()
    for c in ("pct_empty", "pct_full", "pct_renting", "pct_both_zero"):
        out[c] = out[c].astype("float64") * 100
    for c in ("bikes_mean", "docks_mean"):
        out[c] = out[c].astype("float64")
    for c in _INT_COLUMNS:
        out[c] = out[c].astype("float64").round().astype("Int64")
    out["n_obs"] = out["n_obs"].astype("int64")
    out["n_valid"] = out["n_valid"].astype("int64")
    out["bucket_start_utc"] = pd.to_datetime(out["bucket_start_utc"], utc=True).astype(
        "datetime64[ns, UTC]"
    )
    zone = _zone_of(tz, out["system_id"])
    if zone is not None:
        local = []
        offset = []
        for start, z in zip(out["bucket_start_utc"], zone, strict=True):
            here = start.tz_convert(z)
            local.append(here.tz_localize(None))
            offset.append(int(here.utcoffset().total_seconds() // 60))
        out["bucket_start_local"] = pd.to_datetime(local)
        out["utc_offset_min"] = pd.array(offset, dtype="Int16")
    cols = [c for c in AGGREGATE_COLUMNS if c in out.columns]
    return out[cols].reset_index(drop=True)


def check_conservation(aggregated: pd.DataFrame, source: Any) -> None:
    """Raise ``GBFSValidationError`` unless the buckets hold exactly the source rows.

    The sum of ``n_obs`` must equal the number of rows of ``source`` (a frame, an Arrow
    table, a relation or a path): an aggregate that lost or invented an observation is wrong
    whatever its means look like.

    Examples
    --------
    >>> import pandas as pd
    >>> check_conservation(pd.DataFrame({"n_obs": [15, 15]}), pd.DataFrame({"x": range(30)}))
    """
    got, want = (
        int(aggregated["n_obs"].sum()),
        open_table(source, what="check_conservation").count(),
    )
    if got != want:
        raise GBFSValidationError(
            f"aggregation does not conserve observations: sum of n_obs is {got}, source has {want} rows"
        )


def aggregate_levels(
    df: Any,
    *,
    levels: Mapping[str, str] | None = None,
    verify: bool = True,
    **options: object,
) -> dict[str, pd.DataFrame]:
    """The 15-minute, hourly and daily aggregates in one call, each checked for conservation.

    Returns ``{"15m": ..., "1h": ..., "1d": ...}`` (or the ``levels`` you give, name -> freq);
    ``options`` go to `aggregate_availability` (``engine``, ``tz``, ``chunk``...). With
    ``verify`` (the default) each level must conserve the observations, so the three tables
    describe the same rows.

    Examples
    --------
    >>> import pandas as pd
    >>> t = pd.date_range("2026-03-01T00:00Z", periods=200, freq="min")
    >>> df = pd.DataFrame({"system_id": "a", "station_id": "s", "fetched_at": t,
    ...                    "num_bikes_available": 3})
    >>> out = aggregate_levels(df)
    >>> {k: int(v["n_obs"].sum()) for k, v in out.items()}
    {'15m': 200, '1h': 200, '1d': 200}
    """
    source = open_table(df, what="aggregate_levels")
    result = {}
    for name, freq in (levels or LEVELS).items():
        agg = aggregate_availability(source, freq, **options)  # type: ignore[arg-type]
        if verify:
            check_conservation(agg, source)
        result[name] = agg
    return result

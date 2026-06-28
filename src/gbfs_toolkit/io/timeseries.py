"""Longitudinal layer: turn a stream of snapshots into a research data lake.

The library owns the *formatting, deduplication and I/O*; your orchestrator (cron /
Airflow / Dagster) owns the polling loop. Requires the optional ``[parquet]`` extra
(``pyarrow``).

Workflow
--------
1. A poller calls :func:`append_to_parquet` on each fetched snapshot: fast, append-only,
   Hive-partitioned by ``system_id`` / ``date``.
2. Analysis calls :func:`build_availability_panel` to read a system/time window back
   (PyArrow filters partitions *before* loading), de-duplicated and optionally resampled.
3. :func:`calculate_net_flow` turns the panel into period-over-period bike deltas.
"""

from __future__ import annotations

import functools
import hashlib
import uuid
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from gbfs_toolkit.core.models import require_columns
from gbfs_toolkit.core.utils import panel_frame


def _require_pyarrow():
    try:
        import pyarrow  # noqa: F401
        import pyarrow.dataset as ds

        return ds
    except ImportError as e:  # pragma: no cover
        raise ImportError(
            "The longitudinal layer requires pyarrow. Install with "
            "`pip install gbfs-toolkit[parquet]`."
        ) from e


def _as_utc(x: str | pd.Timestamp) -> pd.Timestamp:
    """Coerce to a UTC Timestamp whether the input is naive or already tz-aware."""
    ts = pd.Timestamp(x)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def append_to_parquet(
    df: pd.DataFrame,
    base_path: str | Path,
    *,
    partition_cols: list[str] | tuple[str, ...] = ("system_id", "date"),
) -> None:
    """Append a snapshot to a Hive-partitioned Parquet dataset (append-only, fast).

    A ``date`` column (UTC, ``YYYY-MM-DD``) is derived from ``fetched_at`` when missing,
    for stable daily partitioning. Each call writes a *new* file (unique basename), so
    concurrent pollers never clobber each other; de-duplication happens on read, not write.

    See Also
    --------
    [`generate_manifest`][gbfs_toolkit.generate_manifest] : Manifest of the written archive.
    [`build_availability_panel`][gbfs_toolkit.build_availability_panel] : Read the archive back into a panel.
    """
    ds = _require_pyarrow()
    import pyarrow as pa

    out = df.copy()
    if "date" in partition_cols and "date" not in out.columns:
        out["date"] = pd.to_datetime(out["fetched_at"], utc=True).dt.strftime("%Y-%m-%d")
    table = pa.Table.from_pandas(out, preserve_index=False)
    ds.write_dataset(
        table,
        base_path,
        format="parquet",
        partitioning=list(partition_cols),
        partitioning_flavor="hive",
        basename_template=f"part-{uuid.uuid4().hex}-{{i}}.parquet",
        existing_data_behavior="overwrite_or_ignore",
    )


def build_availability_panel(
    base_path: str | Path,
    *,
    system_id: str | None = None,
    start_time: str | pd.Timestamp | None = None,
    end_time: str | pd.Timestamp | None = None,
    resample_freq: str | None = None,
    dedup: bool = True,
    columns: list[str] | None = None,
    filters: Any = None,
    target_tz: str | None = None,
) -> pd.DataFrame:
    """Read a partitioned dataset into a tidy availability panel.

    Filters by ``system_id`` and the ``date`` partition *before* loading (memory-bounded),
    then de-duplicates redundant polls (same ``station_id`` + ``last_reported``) and
    optionally resamples each station to a fixed frequency (forward-filled).

    Scaling to large lakes
    ----------------------
    For multi-month / multi-city panels that would not fit in memory, push the work down
    into PyArrow:

    - ``columns``: project only the columns you need (the keys ``system_id``,
      ``station_id``, ``fetched_at`` and, when de-duplicating, ``last_reported`` are always
      read). Fewer columns ⇒ less I/O and RAM.
    - ``filters``: an extra ``pyarrow.dataset`` predicate ANDed with the built-in
      system/date filter, applied *before* materialising (row-group pruning). Build it with
      ``import pyarrow.dataset as ds; ds.field("num_bikes_available") == 0``.

    Local time
    ----------
    Pass ``target_tz`` (e.g. ``"America/Los_Angeles"``) to convert ``fetched_at`` /
    ``last_reported`` to that zone **before** any dedup or resample. Resampling tz-aware UTC
    data would otherwise cut "days" at UTC midnight (i.e. mid-afternoon local time),
    silently corrupting diurnal/daily aggregations.

    Returns
    -------
    pandas.DataFrame
        MultiIndexed by ``(system_id, station_id, fetched_at)``, sorted.

    See Also
    --------
    [`availability`][gbfs_toolkit.availability] : A single-snapshot availability frame.
    [`calculate_net_flow`][gbfs_toolkit.calculate_net_flow] : Per-interval flow from this panel.
    [`stockout_episodes`][gbfs_toolkit.stockout_episodes] : Outage episodes from this panel.
    """
    ds = _require_pyarrow()
    dataset = ds.dataset(str(base_path), format="parquet", partitioning="hive")

    start = _as_utc(start_time) if start_time is not None else None
    end = _as_utc(end_time) if end_time is not None else None

    filt = None
    if system_id is not None:
        filt = ds.field("system_id") == system_id
    if start is not None and "date" in dataset.schema.names:
        cond = ds.field("date") >= start.strftime("%Y-%m-%d")
        filt = cond if filt is None else filt & cond
    if end is not None and "date" in dataset.schema.names:
        cond = ds.field("date") <= end.strftime("%Y-%m-%d")
        filt = cond if filt is None else filt & cond
    if filters is not None:
        filt = filters if filt is None else filt & filters

    read_cols = None
    if columns is not None:
        keys = ["system_id", "station_id", "fetched_at"]
        if dedup:
            keys.append("last_reported")
        wanted = list(dict.fromkeys([*keys, *columns]))
        read_cols = [c for c in wanted if c in dataset.schema.names]

    df = dataset.to_table(filter=filt, columns=read_cols).to_pandas()
    if df.empty:
        return df

    df["fetched_at"] = pd.to_datetime(df["fetched_at"], utc=True)
    if "last_reported" in df:
        df["last_reported"] = pd.to_datetime(df["last_reported"], utc=True)
    if target_tz is not None:
        # Convert to local time *before* dedup/resample so daily boundaries are local midnight.
        df["fetched_at"] = df["fetched_at"].dt.tz_convert(target_tz)
        if "last_reported" in df:
            df["last_reported"] = df["last_reported"].dt.tz_convert(target_tz)
    df = df.sort_values(["system_id", "station_id", "fetched_at"])

    if dedup and "last_reported" in df:
        df = df.drop_duplicates(subset=["system_id", "station_id", "last_reported"], keep="last")
    if start is not None:
        df = df[df["fetched_at"] >= start]
    if end is not None:
        df = df[df["fetched_at"] <= end]

    if resample_freq:
        cols = [c for c in ("num_bikes_available", "num_docks_available") if c in df]
        parts = []
        for (sid, stid), g in df.groupby(["system_id", "station_id"], sort=False):
            r = g.set_index("fetched_at")[cols].resample(resample_freq).ffill()
            r["system_id"], r["station_id"] = sid, stid
            parts.append(r.reset_index())
        df = pd.concat(parts, ignore_index=True)

    return df.set_index(["system_id", "station_id", "fetched_at"]).sort_index()


def calculate_net_flow(panel: pd.DataFrame) -> pd.DataFrame:
    """Period-over-period change in available bikes per station.

    Adds ``net_flow``: the Δ in ``num_bikes_available`` vs the previous poll of the same
    station. ``net_flow`` is ``NaN`` across polls where ``last_reported`` did not change (the
    feed re-served an identical observation), so you don't read spurious zero-flows.

    This intentionally reports the **observed flow only**, not its cause. Attributing a flow to
    rebalancing vs. organic demand is not identifiable from availability counts alone: a
    station spike can be a van drop *or* a burst of returns, and system-wide mass conservation
    cannot separate an internal van move from coincident organic trips. Apply your own,
    explicitly-stated heuristic downstream rather than trusting a built-in label.

    .. warning::
       **Aliasing (the polling Nyquist limit).** ``net_flow`` is the *net* change between two
       polls, so any activity that cancels within a polling interval is invisible: a bike
       rented and returned to the same station between snapshots yields Δ=0. Treat the summed
       absolute flow as a **lower bound** on true activity, and poll well below the timescale
       of the dynamics you want to measure.

    Accepts a panel from :func:`build_availability_panel` (MultiIndexed) or a flat frame;
    returns a flat frame with ``system_id, station_id, fetched_at`` columns.

    See Also
    --------
    [`build_availability_panel`][gbfs_toolkit.build_availability_panel] : The panel this consumes.
    [`turnover`][gbfs_toolkit.turnover] : Aggregate absolute flow.
    [`flow_balance`][gbfs_toolkit.flow_balance] : Net source/sink balance.
    """
    df = panel.reset_index() if isinstance(panel.index, pd.MultiIndex) else panel.copy()
    require_columns(
        df,
        ["system_id", "station_id", "fetched_at", "num_bikes_available"],
        what="calculate_net_flow",
    )
    df = df.sort_values(["system_id", "station_id", "fetched_at"])
    grp = df.groupby(["system_id", "station_id"], sort=False)

    df["net_flow"] = grp["num_bikes_available"].diff()
    if "last_reported" in df:
        unchanged = grp["last_reported"].diff().eq(pd.Timedelta(0))
        df.loc[unchanged, "net_flow"] = np.nan
    return df.reset_index(drop=True)


_EPISODE_COLUMNS = [
    "system_id",
    "station_id",
    "kind",
    "start",
    "end",
    "duration_minutes",
    "n_obs",
]


def stockout_episodes(
    panel: pd.DataFrame, *, kinds: tuple[str, ...] = ("empty", "full")
) -> pd.DataFrame:
    """Discrete empty/full episodes per station: the service-quality view of a panel.

    Where :func:`coverage_report` and ``availability_stats`` give *fractions* of time, this
    returns the individual outage **events**: each contiguous run of empty (no bikes) or full
    (no docks) snapshots becomes one row, so you can study how *often* stockouts happen and how
    *long* they last. Durations span the observed snapshots in the run (a single-observation
    episode has duration 0); read them together with :func:`coverage_report`.

    Parameters
    ----------
    panel : pandas.DataFrame
        From :func:`build_availability_panel` (MultiIndexed) or a flat frame with
        ``system_id, station_id, fetched_at, num_bikes_available, num_docks_available``.
    kinds : tuple of {"empty", "full"}
        Which outage types to extract.

    Returns
    -------
    pandas.DataFrame
        One row per episode: ``system_id, station_id, kind, start, end, duration_minutes,
        n_obs`` (sorted by station then start).

    See Also
    --------
    [`detect_frozen_stations`][gbfs_toolkit.detect_frozen_stations] : Find stuck (never-changing) stations.
    [`build_availability_panel`][gbfs_toolkit.build_availability_panel] : The panel this scans.
    """
    df = panel.reset_index() if isinstance(panel.index, pd.MultiIndex) else panel.copy()
    require_columns(
        df,
        ["system_id", "station_id", "fetched_at", "num_bikes_available", "num_docks_available"],
        what="stockout_episodes",
    )
    df = df.sort_values(["system_id", "station_id", "fetched_at"])
    bikes = pd.to_numeric(df["num_bikes_available"], errors="coerce")
    docks = pd.to_numeric(df["num_docks_available"], errors="coerce")
    state = {"empty": bikes <= 0, "full": docks <= 0}

    rows = []
    keys = ["system_id", "station_id"]
    for kind in kinds:
        tmp = df[keys].copy()
        tmp["_flag"] = state[kind].to_numpy()
        # a new run starts whenever the flag changes (groupby shift resets at station bounds)
        shifted = tmp.groupby(keys, sort=False)["_flag"].shift()
        run = (tmp["_flag"] != shifted).cumsum()
        mask = tmp["_flag"].to_numpy()
        active = df[mask].assign(_run=run[mask].to_numpy())
        for (sid, stid, _r), g in active.groupby([*keys, "_run"], sort=False):
            start, end = g["fetched_at"].min(), g["fetched_at"].max()
            rows.append(
                {
                    "system_id": sid,
                    "station_id": stid,
                    "kind": kind,
                    "start": start,
                    "end": end,
                    "duration_minutes": round((end - start).total_seconds() / 60, 1),
                    "n_obs": int(len(g)),
                }
            )
    out = pd.DataFrame(rows, columns=_EPISODE_COLUMNS)
    return out.sort_values(["system_id", "station_id", "start"]).reset_index(drop=True)


def turnover(
    panel: pd.DataFrame, *, freq: str = "1D", normalize: str | None = None
) -> pd.DataFrame:
    """Per-station activity proxy: summed absolute net flow per period.

    A cheap, model-free measure of how busy a station is. It is a **lower bound**: by the
    aliasing argument in :func:`calculate_net_flow`, trips that cancel within a polling interval
    are invisible. Use it for relative comparison (which stations / days are busier), not as a
    trip count.

    Parameters
    ----------
    freq : str, default "1D"
        Aggregation bin (a pandas offset alias).
    normalize : {None, "capacity"}
        If ``"capacity"``, divide each station's turnover by its capacity (requires a
        ``capacity`` column in ``panel``); comparable across stations of different sizes.

    Returns
    -------
    pandas.DataFrame
        ``system_id, station_id, period, turnover`` (Σ ``|net_flow|`` over each ``freq`` bin).

    See Also
    --------
    [`calculate_net_flow`][gbfs_toolkit.calculate_net_flow] : The per-interval flow this sums.
    [`flow_balance`][gbfs_toolkit.flow_balance] : Signed instead of absolute flow.
    """
    flow = calculate_net_flow(panel).dropna(subset=["net_flow"])
    if flow.empty:
        return pd.DataFrame(columns=["system_id", "station_id", "period", "turnover"])
    flow = flow.assign(
        period=pd.to_datetime(flow["fetched_at"]).dt.floor(freq), activity=flow["net_flow"].abs()
    )
    out = (
        flow.groupby(["system_id", "station_id", "period"])["activity"]
        .sum()
        .rename("turnover")
        .reset_index()
    )
    if normalize == "capacity":
        require_columns(flow, ["capacity"], what='turnover(normalize="capacity")')
        caps = flow.groupby(["system_id", "station_id"])["capacity"].first()
        out = out.merge(caps.rename("capacity"), on=["system_id", "station_id"])
        out["turnover"] = out["turnover"] / out["capacity"].where(out["capacity"] > 0)
        out = out.drop(columns="capacity")
    return out


def flow_balance(panel: pd.DataFrame) -> pd.DataFrame:
    """Per-station inflow / outflow split and source↔sink balance.

    Splits :func:`calculate_net_flow` into bikes gained (``inflow`` = Σ positive Δ) and lost
    (``outflow`` = Σ |negative Δ|), with ``balance = outflow / inflow``: ``>1`` ⇒ a net
    *source* (more departures than arrivals, a morning residential origin), ``<1`` ⇒ a net
    *sink* (destination). Like turnover, these are lower bounds (intra-interval trips cancel).

    Returns
    -------
    pandas.DataFrame
        Indexed by ``(system_id, station_id)``: ``inflow``, ``outflow``, ``net``, ``balance``.

    See Also
    --------
    [`calculate_net_flow`][gbfs_toolkit.calculate_net_flow] : The per-interval flow this nets.
    [`turnover`][gbfs_toolkit.turnover] : Absolute instead of signed flow.
    """
    flow = calculate_net_flow(panel).dropna(subset=["net_flow"])
    keys = ["system_id", "station_id"]
    if flow.empty:
        return pd.DataFrame(
            columns=["inflow", "outflow", "net", "balance"],
            index=pd.MultiIndex.from_arrays([[], []], names=keys),
        )
    f = flow["net_flow"]
    work = flow[keys].assign(_in=f.clip(lower=0), _out=(-f).clip(lower=0))
    out = work.groupby(keys).agg(inflow=("_in", "sum"), outflow=("_out", "sum"))
    out["net"] = out["inflow"] - out["outflow"]
    out["balance"] = (out["outflow"] / out["inflow"].where(out["inflow"] > 0)).round(3)
    return out


_FROZEN_COLUMNS = ["n_obs", "longest_const_run_hours", "frozen_value", "is_frozen"]


def _run_stats(df: pd.DataFrame, keys: list[str], col: str) -> pd.DataFrame:
    """Per-station run statistics for one column: longest constant run + whole-series constancy."""
    tmp = df[keys].copy()
    tmp["_v"] = pd.to_numeric(df[col], errors="coerce").to_numpy()
    tmp["_t"] = df["fetched_at"].to_numpy()
    changed = tmp["_v"] != tmp.groupby(keys, sort=False)["_v"].shift()
    tmp["_run"] = changed.cumsum()
    runs = (
        tmp.groupby([*keys, "_run"], sort=False)
        .agg(start=("_t", "min"), end=("_t", "max"), value=("_v", "first"))
        .reset_index()
    )
    runs["hours"] = (runs["end"] - runs["start"]).dt.total_seconds() / 3600
    longest = runs.loc[runs.groupby(keys)["hours"].idxmax()].set_index(keys)
    return pd.DataFrame(
        {
            "longest_run_hours": longest["hours"],
            "run_value": longest["value"],
            "constant": tmp.groupby(keys)["_v"].nunique(dropna=False) <= 1,
        }
    )


def detect_frozen_stations(
    panel: pd.DataFrame,
    *,
    value_col: str = "num_bikes_available",
    columns: tuple[str, ...] | None = None,
    min_run_hours: float = 6.0,
    active_hours: tuple[int, int] | None = (6, 22),
    strict: bool = False,
) -> pd.DataFrame:
    """Flag "frozen" stations: a value stuck unchanged while the feed keeps updating.

    Distinct from staleness (D3, where ``last_reported`` itself goes stale) and from a genuine
    stockout: here the feed is fresh but the value never moves, the signature of a dead sensor
    or a station the operator forgot. Restricting to ``active_hours`` (local hour of
    ``fetched_at`` as stored) avoids flagging the legitimate overnight flatline.

    Parameters
    ----------
    value_col : str, default "num_bikes_available"
        The column expected to vary (used when ``columns`` is not given).
    columns : tuple of str, optional
        Require *all* these columns to be frozen, e.g. ``("num_bikes_available",
        "num_docks_available")``: a stricter, both-counters-stuck signal. Defaults to
        ``(value_col,)``.
    min_run_hours : float, default 6
        Minimum span (of an unchanged run, or of the whole series in ``strict`` mode) to call a
        station frozen.
    active_hours : (int, int) or None, default (6, 22)
        Keep only observations in ``[lo, hi)`` local hours; ``None`` to use all.
    strict : bool, default False
        If ``True``, a column counts as frozen only when it **never changes** across the entire
        observed window (span ≥ ``min_run_hours``), not merely a long constant *run*. This
        matches a "never-moved" zombie definition; the default (``False``) is the broader
        "stuck for ≥ ``min_run_hours`` at some point".

    Returns
    -------
    pandas.DataFrame
        Indexed by ``(system_id, station_id)``: ``n_obs``, ``longest_const_run_hours``,
        ``frozen_value`` (for the first column), ``is_frozen``.

    See Also
    --------
    [`stockout_episodes`][gbfs_toolkit.stockout_episodes] : Genuine outage episodes.
    """
    cols = list(columns) if columns else [value_col]
    df = panel.reset_index() if isinstance(panel.index, pd.MultiIndex) else panel.copy()
    require_columns(
        df, ["system_id", "station_id", "fetched_at", *cols], what="detect_frozen_stations"
    )
    df = df[["system_id", "station_id", "fetched_at", *cols]].copy()
    df["fetched_at"] = pd.to_datetime(df["fetched_at"])
    if active_hours is not None:
        lo, hi = active_hours
        hour = df["fetched_at"].dt.hour
        df = df[(hour >= lo) & (hour < hi)]
    keys = ["system_id", "station_id"]
    if df.empty:
        return pd.DataFrame(columns=_FROZEN_COLUMNS).rename_axis(keys)
    df = df.sort_values([*keys, "fetched_at"])

    span = df.groupby(keys)["fetched_at"].agg(first="min", last="max", n_obs="size")
    span_hours = (span["last"] - span["first"]).dt.total_seconds() / 3600

    frozen = None
    primary = None
    for i, col in enumerate(cols):
        rs = _run_stats(df, keys, col)
        if strict:
            col_frozen = rs["constant"] & (span_hours >= min_run_hours)
        else:
            col_frozen = rs["longest_run_hours"] >= min_run_hours
        frozen = col_frozen if frozen is None else (frozen & col_frozen)
        if i == 0:
            primary = rs

    assert primary is not None and frozen is not None  # at least one column is always processed
    out = pd.DataFrame(
        {
            "n_obs": span["n_obs"].astype(int),
            "longest_const_run_hours": primary["longest_run_hours"].round(2),
            "frozen_value": primary["run_value"],
            "is_frozen": frozen.reindex(span.index).fillna(False),
        }
    )
    return out[_FROZEN_COLUMNS]


def coverage_report(
    panel: pd.DataFrame, *, expected_freq: str = "5min", level: str = "station"
) -> pd.DataFrame:
    """Longitudinal coverage: quantify missingness *before* you model.

    Operators go offline and scrapers crash; ``calculate_net_flow`` / clustering silently
    assume continuity. With ``level="station"`` this reports how complete each station's
    series is, against the system-wide observation window (so a station that dropped out
    shows low uptime). With ``level="system"`` it returns one row per system, the summary a
    paper's "Data and methods" section needs: window, cadence, cadence jitter and overall
    yield.

    Parameters
    ----------
    panel : pandas.DataFrame
        A panel from :func:`build_availability_panel` (MultiIndexed) or a flat frame with
        ``system_id, station_id, fetched_at``.
    expected_freq : str, default "5min"
        Your intended polling cadence (a pandas offset alias).
    level : {"station", "system"}, default "station"
        ``"station"`` returns the per-station coverage; ``"system"`` returns a per-system
        summary (median cadence, cadence jitter, yield).

    Returns
    -------
    pandas.DataFrame
        For ``level="station"``, indexed by ``(system_id, station_id)``:
        ``expected_snapshots, actual_snapshots, uptime_pct, longest_gap_minutes``.
        For ``level="system"``, indexed by ``system_id``: ``global_start, global_end,
        n_stations, total_snapshots, median_cadence_s, cadence_jitter_s,
        station_hours_yield_pct``.

    See Also
    --------
    [`audit_feed`][gbfs_toolkit.audit_feed] : The audit behind the report.
    [`generate_manifest`][gbfs_toolkit.generate_manifest] : Manifest of an archived collection.

    Examples
    --------
    >>> import pandas as pd
    >>> panel = pd.DataFrame({
    ...     "system_id": "s", "station_id": ["a", "a", "b"],
    ...     "fetched_at": pd.to_datetime(
    ...         ["2026-01-01T00:00Z", "2026-01-01T00:05Z", "2026-01-01T00:00Z"]),
    ... })
    >>> int(coverage_report(panel, level="system")["total_snapshots"].iloc[0])
    2
    """
    if level not in ("station", "system"):
        raise ValueError(f"level must be 'station' or 'system', got {level!r}")
    df = panel.reset_index() if isinstance(panel.index, pd.MultiIndex) else panel.copy()
    require_columns(df, ["system_id", "station_id", "fetched_at"], what="coverage_report")
    df = df[["system_id", "station_id", "fetched_at"]].copy()
    df["fetched_at"] = pd.to_datetime(df["fetched_at"])
    step = pd.Timedelta(expected_freq)

    if level == "system":
        rows = []
        for sid, sysdf in df.groupby("system_id", sort=False):
            t0, t1 = sysdf["fetched_at"].min(), sysdf["fetched_at"].max()
            snapshots = sysdf["fetched_at"].drop_duplicates().sort_values()
            deltas = snapshots.diff().dropna().dt.total_seconds()
            n_stations = int(sysdf["station_id"].nunique())
            expected = int((t1 - t0) / step) + 1 if t1 > t0 else 1
            actual_pairs = len(sysdf[["station_id", "fetched_at"]].drop_duplicates())
            denom = expected * n_stations
            median_dt = float(deltas.median()) if len(deltas) else float("nan")
            rows.append(
                {
                    "system_id": sid,
                    "global_start": t0,
                    "global_end": t1,
                    "n_stations": n_stations,
                    "total_snapshots": int(len(snapshots)),
                    "median_cadence_s": round(median_dt, 1),
                    "cadence_jitter_s": round(float((deltas - median_dt).abs().median()), 1)
                    if len(deltas)
                    else float("nan"),
                    "station_hours_yield_pct": round(min(1.0, actual_pairs / denom) * 100, 1)
                    if denom
                    else float("nan"),
                }
            )
        if not rows:
            return pd.DataFrame(
                columns=[
                    "global_start",
                    "global_end",
                    "n_stations",
                    "total_snapshots",
                    "median_cadence_s",
                    "cadence_jitter_s",
                    "station_hours_yield_pct",
                ],
                index=pd.Index([], name="system_id"),
            )
        return pd.DataFrame(rows).set_index("system_id")

    rows = []
    for sid, sysdf in df.groupby("system_id", sort=False):
        t0, t1 = sysdf["fetched_at"].min(), sysdf["fetched_at"].max()
        expected = int((t1 - t0) / step) + 1 if t1 > t0 else 1
        for stid, g in sysdf.groupby("station_id", sort=False):
            ts = g["fetched_at"].drop_duplicates().sort_values()
            actual = int(len(ts))
            gaps = ts.diff().dropna()
            longest = gaps.max().total_seconds() / 60 if len(gaps) else 0.0
            rows.append(
                {
                    "system_id": sid,
                    "station_id": stid,
                    "expected_snapshots": expected,
                    "actual_snapshots": actual,
                    "uptime_pct": round(min(1.0, actual / expected) * 100, 1),
                    "longest_gap_minutes": round(float(longest), 1),
                }
            )
    if not rows:
        return pd.DataFrame(
            columns=["expected_snapshots", "actual_snapshots", "uptime_pct", "longest_gap_minutes"],
            index=pd.MultiIndex.from_arrays([[], []], names=["system_id", "station_id"]),
        )
    return pd.DataFrame(rows).set_index(["system_id", "station_id"])


def generate_manifest(lake_dir: str | Path, *, chunk_size: int = 1 << 20) -> dict:
    """A cryptographic manifest of a Parquet lake, for citable, reproducible datasets.

    Walks every ``*.parquet`` partition file, records its SHA-256 and size, and summarises
    the dataset (systems, date span, row count). Drop the returned dict next to a Zenodo /
    Dataverse deposit so a reviewer can verify byte-for-byte what was analysed.

    Returns
    -------
    dict
        ``gbfs_toolkit_version``, ``generated_at`` (UTC ISO), ``n_files``, ``total_bytes``,
        ``total_rows``, ``system_ids``, ``min_date``, ``max_date``, and ``files`` (a sorted
        list of ``{path, sha256, bytes}`` with paths relative to ``lake_dir``).

    See Also
    --------
    [`append_to_parquet`][gbfs_toolkit.append_to_parquet] : The append step it documents.
    [`coverage_report`][gbfs_toolkit.coverage_report] : Per-feed coverage summary.
    """
    from gbfs_toolkit import __version__

    base = Path(lake_dir)
    files = []
    for p in sorted(base.rglob("*.parquet")):
        h = hashlib.sha256()
        with p.open("rb") as fh:
            for block in iter(functools.partial(fh.read, chunk_size), b""):
                h.update(block)
        files.append(
            {"path": str(p.relative_to(base)), "sha256": h.hexdigest(), "bytes": p.stat().st_size}
        )

    manifest: dict[str, Any] = {
        "gbfs_toolkit_version": __version__,
        "generated_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "n_files": len(files),
        "total_bytes": sum(f["bytes"] for f in files),
        "files": files,
    }
    try:  # dataset-level summary (best-effort; needs a readable dataset)
        ds = _require_pyarrow()
        dataset = ds.dataset(str(base), format="parquet", partitioning="hive")
        names = dataset.schema.names
        manifest["total_rows"] = int(dataset.count_rows())
        cols = [c for c in ("system_id", "date") if c in names]
        if cols:
            meta = dataset.to_table(columns=cols).to_pandas()
            if "system_id" in meta:
                manifest["system_ids"] = sorted(meta["system_id"].dropna().unique().tolist())
            if "date" in meta and len(meta):
                manifest["min_date"] = str(meta["date"].min())
                manifest["max_date"] = str(meta["date"].max())
    except Exception:  # noqa: BLE001 (summary is best-effort; the hashes are the point)
        pass
    return manifest


def add_local_time(
    panel: pd.DataFrame, tz_name: str, *, time_col: str = "fetched_at", new_col: str = "local_time"
) -> pd.DataFrame:
    """Add a local-time column to a panel, handling the index correctly.

    Converting a UTC timestamp to local time is the first step of any diurnal analysis,
    and doing it on a MultiIndexed panel by hand (``reset_index`` then ``tz_convert`` then
    ``set_index``) is a recurring papercut. This flattens the panel and appends one
    tz-aware ``new_col`` in ``tz_name``, leaving ``time_col`` (UTC) untouched.

    Parameters
    ----------
    panel : pandas.DataFrame
        Any panel/frame with a tz-aware (or UTC-coercible) ``time_col``.
    tz_name : str
        An IANA zone, e.g. ``"Europe/Paris"`` or ``"America/New_York"``.
    time_col, new_col : str
        Source UTC column and the local-time column to add.

    Returns
    -------
    pandas.DataFrame
        A flattened copy of ``panel`` with the added ``new_col``.

    See Also
    --------
    [`build_availability_panel`][gbfs_toolkit.build_availability_panel] : Build a panel already in local time via ``target_tz``.
    [`resample_panel`][gbfs_toolkit.resample_panel] : Put the panel on a fixed time grid.

    Examples
    --------
    >>> import pandas as pd
    >>> df = pd.DataFrame({"fetched_at": pd.to_datetime(["2026-01-01T08:00Z"])})
    >>> int(add_local_time(df, "Europe/Paris")["local_time"].dt.hour.iloc[0])
    9
    """
    df = panel_frame(panel)
    require_columns(df, [time_col], what="add_local_time")
    out = df.copy()
    out[new_col] = pd.to_datetime(out[time_col], utc=True).dt.tz_convert(tz_name)
    return out


def resample_panel(
    panel: pd.DataFrame,
    freq: str = "15min",
    *,
    time_col: str = "fetched_at",
    by: tuple[str, ...] = ("system_id", "station_id"),
) -> pd.DataFrame:
    """Resample each station series onto a fixed time grid, carrying the last state forward.

    Availability is a step function (a station's count holds until the next change), so a
    panel polled at irregular instants must be aligned to a regular grid before clustering,
    correlation or plotting. Doing this per station with ``groupby().resample().ffill()``
    is four brittle lines that routinely break nullable dtypes; this is the one-call,
    dtype-safe version. It carries the last observed state forward (it does not invent
    values), so it is alignment, not imputation.

    Parameters
    ----------
    panel : pandas.DataFrame
        Panel/frame with the grouping columns in ``by`` and a ``time_col``.
    freq : str, default "15min"
        Target grid (a pandas offset alias).
    time_col : str, default "fetched_at"
        Timestamp column.
    by : tuple of str, default ("system_id", "station_id")
        Grouping keys present in ``panel`` (missing keys are ignored).

    Returns
    -------
    pandas.DataFrame
        A flat panel on the ``freq`` grid, last-observation-carried-forward per group.

    See Also
    --------
    [`build_availability_panel`][gbfs_toolkit.build_availability_panel] : Read and resample a Parquet lake in one step.
    [`insert_explicit_gaps`][gbfs_toolkit.insert_explicit_gaps] : Mark collection outages instead of filling them.
    [`extract_snapshot_asof`][gbfs_toolkit.extract_snapshot_asof] : Take a single cross-section.

    Examples
    --------
    >>> import pandas as pd
    >>> panel = pd.DataFrame({
    ...     "station_id": "a",
    ...     "fetched_at": pd.to_datetime(["2026-01-01T00:00Z", "2026-01-01T00:30Z"]),
    ...     "num_bikes_available": [5, 8],
    ... })
    >>> out = resample_panel(panel, "15min")
    >>> out["num_bikes_available"].tolist()
    [5, 5, 8]
    """
    df = panel_frame(panel)
    keys = [k for k in by if k in df.columns]
    require_columns(df, [*keys, time_col], what="resample_panel")
    out = df.copy()
    out[time_col] = pd.to_datetime(out[time_col], utc=True)
    if not keys:
        resampled = out.set_index(time_col).sort_index().resample(freq).ffill()
        return resampled.reset_index()
    parts = []
    for kv, g in out.groupby(keys, sort=False):
        block = g.drop(columns=keys).set_index(time_col).sort_index().resample(freq).ffill()
        block = block.reset_index()
        for key, value in zip(keys, kv if isinstance(kv, tuple) else (kv,), strict=True):
            block[key] = value
        parts.append(block)
    cols = [*keys, time_col, *[c for c in out.columns if c not in keys and c != time_col]]
    return pd.concat(parts, ignore_index=True)[cols]


def insert_explicit_gaps(
    panel: pd.DataFrame,
    *,
    expected_freq: str = "5min",
    tolerance: str = "15min",
    time_col: str = "fetched_at",
    by: tuple[str, ...] = ("system_id", "station_id"),
) -> pd.DataFrame:
    """Insert ``NaN`` rows where collection stalled, so plots show the outage honestly.

    When a scraper dies on Friday and resumes Monday, a line plot draws a misleading
    straight segment across the gap. Inserting an explicit ``NaN`` row in each gap longer
    than ``tolerance`` forces a visual break (and stops rolling statistics bridging the
    hole). Purely descriptive: it makes missingness explicit, it does not fill it.

    Parameters
    ----------
    panel : pandas.DataFrame
        Panel/frame with the grouping columns in ``by`` and a ``time_col``.
    expected_freq : str, default "5min"
        The intended cadence (documented for intent; the test is against ``tolerance``).
    tolerance : str, default "15min"
        Gaps strictly larger than this get a ``NaN`` marker row at their midpoint.
    time_col, by : see :func:`resample_panel`.

    Returns
    -------
    pandas.DataFrame
        A flat copy of ``panel`` with one ``NaN``-valued row inserted per detected gap.

    See Also
    --------
    [`coverage_report`][gbfs_toolkit.coverage_report] : Quantify the same gaps numerically.
    [`resample_panel`][gbfs_toolkit.resample_panel] : Carry state across gaps instead of marking them.

    Examples
    --------
    >>> import pandas as pd
    >>> panel = pd.DataFrame({
    ...     "station_id": "a",
    ...     "fetched_at": pd.to_datetime(
    ...         ["2026-01-01T00:00Z", "2026-01-01T00:05Z", "2026-01-01T02:00Z"]),
    ...     "num_bikes_available": [5, 4, 6],
    ... })
    >>> out = insert_explicit_gaps(panel)
    >>> len(out), int(out["num_bikes_available"].isna().sum())
    (4, 1)
    """
    df = panel_frame(panel).copy()
    keys = [k for k in by if k in df.columns]
    require_columns(df, [*keys, time_col], what="insert_explicit_gaps")
    df[time_col] = pd.to_datetime(df[time_col], utc=True)
    df = df.sort_values([*keys, time_col]) if keys else df.sort_values(time_col)
    tol = pd.Timedelta(tolerance)
    value_cols = [c for c in df.columns if c not in keys and c != time_col]

    gap_rows = []
    grouped = df.groupby(keys, sort=False) if keys else [((), df)]
    for _, g in grouped:
        g = g.reset_index(drop=True)
        dt = g[time_col].diff()
        for i in np.where((dt > tol).to_numpy())[0]:
            prev, nxt = g.iloc[i - 1], g.iloc[i]
            row = {k: prev[k] for k in keys}
            row[time_col] = prev[time_col] + (nxt[time_col] - prev[time_col]) / 2
            for c in value_cols:
                row[c] = np.nan
            gap_rows.append(row)
    if gap_rows:
        df = pd.concat([df, pd.DataFrame(gap_rows)], ignore_index=True)
        df = df.sort_values([*keys, time_col]) if keys else df.sort_values(time_col)
    return df.reset_index(drop=True)


def extract_snapshot_asof(
    panel: pd.DataFrame,
    target_time: str | pd.Timestamp,
    *,
    tolerance: str = "10min",
    time_col: str = "fetched_at",
    by: tuple[str, ...] = ("system_id", "station_id"),
) -> pd.DataFrame:
    """Extract the city's state at one instant: each station's last reading at or before ``T``.

    Stations answer at slightly different seconds, so "the state at 08:00" is not a clean
    slice. This returns, per station, the most recent observation in
    ``[target_time - tolerance, target_time]``, the cross-section a snapshot map or a
    point-in-time comparison needs, without a hand-rolled ``merge_asof``.

    Parameters
    ----------
    panel : pandas.DataFrame
        Panel/frame with the grouping columns in ``by`` and a ``time_col``.
    target_time : str or pandas.Timestamp
        The instant to reconstruct (naive is read as UTC).
    tolerance : str, default "10min"
        How far before ``target_time`` a reading may be and still count.
    time_col, by : see :func:`resample_panel`.

    Returns
    -------
    pandas.DataFrame
        One row per group: its latest reading within the window (empty if none qualify).

    See Also
    --------
    [`resample_panel`][gbfs_toolkit.resample_panel] : Align the whole panel to a grid instead.
    [`to_wide_matrix`][gbfs_toolkit.to_wide_matrix] : Pivot the panel to a station-by-time matrix.

    Examples
    --------
    >>> import pandas as pd
    >>> panel = pd.DataFrame({
    ...     "station_id": ["a", "a", "b"],
    ...     "fetched_at": pd.to_datetime(
    ...         ["2026-01-01T07:59Z", "2026-01-01T08:30Z", "2026-01-01T08:00Z"]),
    ...     "num_bikes_available": [3, 9, 7],
    ... })
    >>> snap = extract_snapshot_asof(panel, "2026-01-01T08:00Z").set_index("station_id")
    >>> int(snap.loc["a", "num_bikes_available"])
    3
    """
    df = panel_frame(panel).copy()
    keys = [k for k in by if k in df.columns]
    require_columns(df, [*keys, time_col], what="extract_snapshot_asof")
    df[time_col] = pd.to_datetime(df[time_col], utc=True)
    target = _as_utc(target_time)
    window = df[(df[time_col] <= target) & (df[time_col] >= target - pd.Timedelta(tolerance))]
    if window.empty:
        return df.iloc[:0].reset_index(drop=True)
    if not keys:
        return df.loc[[window[time_col].idxmax()]].reset_index(drop=True)
    idx = window.groupby(keys, sort=False)[time_col].idxmax()
    return df.loc[idx].reset_index(drop=True)


def to_wide_matrix(
    panel: pd.DataFrame,
    *,
    value_col: str = "num_bikes_available",
    time_col: str = "fetched_at",
    station_col: str = "station_id",
) -> pd.DataFrame:
    """Pivot a long panel into a time-by-station matrix.

    The "long/tidy" panel is right for storage but most external tools (scikit-learn,
    a correlation matrix, a heatmap) want the "wide" form: rows are timestamps, columns
    are stations, cells are ``value_col``. ``pivot_table`` does this but leaves fiddly
    column-index names to clean up; this returns a flat, ready-to-use matrix.

    Parameters
    ----------
    panel : pandas.DataFrame
        Long panel/frame with ``time_col``, ``station_col`` and ``value_col``.
    value_col, time_col, station_col : str
        The cell value, the row key and the column key.

    Returns
    -------
    pandas.DataFrame
        Indexed by ``time_col``, one column per station (duplicates averaged).

    See Also
    --------
    [`extract_snapshot_asof`][gbfs_toolkit.extract_snapshot_asof] : Take a single row of this matrix.
    [`resample_panel`][gbfs_toolkit.resample_panel] : Put the rows on a regular grid first.

    Examples
    --------
    >>> import pandas as pd
    >>> panel = pd.DataFrame({
    ...     "station_id": ["a", "b", "a", "b"],
    ...     "fetched_at": pd.to_datetime(
    ...         ["2026-01-01T08:00Z"] * 2 + ["2026-01-01T09:00Z"] * 2),
    ...     "num_bikes_available": [5, 2, 3, 8],
    ... })
    >>> to_wide_matrix(panel).shape
    (2, 2)
    """
    df = panel_frame(panel)
    require_columns(df, [time_col, station_col, value_col], what="to_wide_matrix")
    wide = df.pivot_table(index=time_col, columns=station_col, values=value_col, aggfunc="mean")
    wide.columns.name = None
    return wide

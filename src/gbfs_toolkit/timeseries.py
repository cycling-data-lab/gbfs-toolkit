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

import hashlib
import uuid
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from gbfs_toolkit.models import require_columns


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
    """
    flow = calculate_net_flow(panel).dropna(subset=["net_flow"])
    keys = ["system_id", "station_id"]
    if flow.empty:
        return pd.DataFrame(columns=["inflow", "outflow", "net", "balance"]).rename_axis(keys)
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

    out = pd.DataFrame(
        {
            "n_obs": span["n_obs"].astype(int),
            "longest_const_run_hours": primary["longest_run_hours"].round(2),
            "frozen_value": primary["run_value"],
            "is_frozen": frozen.reindex(span.index).fillna(False),
        }
    )
    return out[_FROZEN_COLUMNS]


def coverage_report(panel: pd.DataFrame, *, expected_freq: str = "5min") -> pd.DataFrame:
    """Per-station longitudinal coverage: quantify missingness *before* you model.

    Operators go offline and scrapers crash; ``calculate_net_flow`` / clustering silently
    assume continuity. This reports how complete each station's series is, against the
    system-wide observation window (so a station that dropped out shows low uptime).

    Parameters
    ----------
    panel : pandas.DataFrame
        A panel from :func:`build_availability_panel` (MultiIndexed) or a flat frame with
        ``system_id, station_id, fetched_at``.
    expected_freq : str, default "5min"
        Your intended polling cadence (a pandas offset alias).

    Returns
    -------
    pandas.DataFrame
        Indexed by ``(system_id, station_id)``: ``expected_snapshots``, ``actual_snapshots``,
        ``uptime_pct``, ``longest_gap_minutes``.
    """
    df = panel.reset_index() if isinstance(panel.index, pd.MultiIndex) else panel.copy()
    require_columns(df, ["system_id", "station_id", "fetched_at"], what="coverage_report")
    df = df[["system_id", "station_id", "fetched_at"]].copy()
    df["fetched_at"] = pd.to_datetime(df["fetched_at"])
    step = pd.Timedelta(expected_freq)

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
    """
    from gbfs_toolkit import __version__

    base = Path(lake_dir)
    files = []
    for p in sorted(base.rglob("*.parquet")):
        h = hashlib.sha256()
        with p.open("rb") as fh:
            for block in iter(lambda fh=fh: fh.read(chunk_size), b""):
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


def _panel_frame(panel: pd.DataFrame) -> pd.DataFrame:
    """Flatten a MultiIndexed panel to a frame with the index levels as columns."""
    return panel.reset_index() if isinstance(panel.index, pd.MultiIndex) else panel.copy()


def service_reliability_index(
    panel: pd.DataFrame,
    *,
    freq: str = "1h",
    min_bikes: int = 1,
    min_docks: int = 1,
) -> pd.DataFrame:
    """Empirical level-of-service probability per station and time-of-day.

    For each station and each time-of-day bucket (width ``freq``), the fraction of observations
    with at least ``min_bikes`` bikes, with at least ``min_docks`` docks, and with both at once.
    This is the service view a mode-shift study needs ("can a user find a bike *and* a dock at
    08:00?"), which an availability mean hides.

    Parameters
    ----------
    panel : pandas.DataFrame
        From :func:`build_availability_panel` (MultiIndexed) or a flat frame with
        ``system_id, station_id, fetched_at, num_bikes_available, num_docks_available``.
        Convert to local time (``build_availability_panel(target_tz=...)``) first, so the buckets
        are local hours.
    freq : str, default "1h"
        Fixed time-of-day bucket width (a pandas offset alias such as ``"1h"`` or ``"30min"``).
    min_bikes, min_docks : int
        Availability thresholds for "service available".

    Returns
    -------
    pandas.DataFrame
        ``system_id, station_id, time_of_day`` (a ``Timedelta`` since local midnight),
        ``prob_bikes_avail, prob_docks_avail, prob_full_service, n_obs``.

    References
    ----------
    Vogel, Greiser and Mattfeld (2011), Understanding bike-sharing systems using data mining.
    """
    df = _panel_frame(panel)
    require_columns(
        df,
        ["system_id", "station_id", "fetched_at", "num_bikes_available", "num_docks_available"],
        what="service_reliability_index",
    )
    ts = pd.to_datetime(df["fetched_at"])
    step_min = pd.tseries.frequencies.to_offset(freq).nanos / 6e10
    minutes = ts.dt.hour * 60 + ts.dt.minute + ts.dt.second / 60
    bucket = np.floor(minutes / step_min) * step_min
    bikes_ok = pd.to_numeric(df["num_bikes_available"], errors="coerce") >= min_bikes
    docks_ok = pd.to_numeric(df["num_docks_available"], errors="coerce") >= min_docks
    work = pd.DataFrame(
        {
            "system_id": df["system_id"].to_numpy(),
            "station_id": df["station_id"].to_numpy(),
            "time_of_day": pd.to_timedelta(bucket.to_numpy(), unit="m"),
            "_bikes": bikes_ok.to_numpy(),
            "_docks": docks_ok.to_numpy(),
        }
    )
    work["_full"] = work["_bikes"] & work["_docks"]
    out = (
        work.groupby(["system_id", "station_id", "time_of_day"])
        .agg(
            prob_bikes_avail=("_bikes", "mean"),
            prob_docks_avail=("_docks", "mean"),
            prob_full_service=("_full", "mean"),
            n_obs=("_full", "size"),
        )
        .reset_index()
    )
    return out


def temporal_autocorrelation(
    panel: pd.DataFrame,
    *,
    lags: tuple[int, ...] = (1, 24, 168),
    freq: str = "1h",
    column: str = "num_bikes_available",
) -> pd.DataFrame:
    """Per-station autocorrelation of availability at fixed lags (hour, day, week).

    Each station's series is resampled to ``freq`` (mean) and correlated with itself at each
    lag. High autocorrelation at lag 24 (one day) marks a regular commuter rhythm; low
    autocorrelation everywhere marks an irregular or recreational station. A deterministic,
    descriptive precursor to (or substitute for) clustering.

    Parameters
    ----------
    panel : pandas.DataFrame
        From :func:`build_availability_panel` or a flat frame with ``system_id, station_id,
        fetched_at`` and ``column``.
    lags : tuple of int, default (1, 24, 168)
        Lags in units of ``freq`` (with the default ``"1h"``: hour, day, week).
    freq : str, default "1h"
        Resampling frequency.
    column : str, default "num_bikes_available"
        Series to correlate.

    Returns
    -------
    pandas.DataFrame
        ``system_id, station_id`` and one ``acf_lag_<k>`` column per lag (``NaN`` when the
        resampled series is too short for that lag).

    References
    ----------
    O'Brien, Cheshire and Batty (2014), Mining bike-sharing data for sustainable transport.
    """
    df = _panel_frame(panel)
    require_columns(
        df, ["system_id", "station_id", "fetched_at", column], what="temporal_autocorrelation"
    )
    df = df.sort_values(["system_id", "station_id", "fetched_at"])
    rows = []
    for (sid, stid), g in df.groupby(["system_id", "station_id"], sort=False):
        series = (
            pd.to_numeric(g.set_index("fetched_at")[column], errors="coerce").resample(freq).mean()
        )
        row: dict[str, Any] = {"system_id": sid, "station_id": stid}
        for lag in lags:
            row[f"acf_lag_{lag}"] = (
                series.autocorr(lag) if int(series.notna().sum()) > lag + 1 else np.nan
            )
        rows.append(row)
    return pd.DataFrame(rows)


def cumulative_imbalance(panel: pd.DataFrame, *, reset: str | None = "1D") -> pd.DataFrame:
    """Per-station cumulative net flow (drift) since each period's start.

    The running sum of the observed ``net_flow`` reveals structural sources and sinks: a station
    whose drift trends steadily negative over a day is being drained faster than it refills. By
    default the drift resets at each period boundary (``reset="1D"``); pass ``reset=None`` for a
    single running total over the whole panel.

    This is a descriptive reconstruction of the *observed* inventory change. It does not attribute
    the change to rebalancing versus organic demand, which is not identifiable from
    station-aggregate counts (see :func:`calculate_net_flow` and the methodology).

    Returns
    -------
    pandas.DataFrame
        The :func:`calculate_net_flow` frame plus a ``cumulative_drift`` column.
    """
    flow = calculate_net_flow(panel).sort_values(["system_id", "station_id", "fetched_at"])
    filled = flow["net_flow"].fillna(0.0)
    groupers = [flow["system_id"], flow["station_id"]]
    if reset:
        groupers.append(pd.to_datetime(flow["fetched_at"]).dt.floor(reset))
    flow["cumulative_drift"] = filled.groupby(groupers).cumsum()
    return flow.reset_index(drop=True)


def aliasing_vulnerability(panel: pd.DataFrame) -> pd.DataFrame:
    """Per-station risk that the polling cadence misses short-timescale dynamics.

    A diagnostic for the polling Nyquist limit (see :func:`calculate_net_flow`). For each station
    it measures how often consecutive non-zero net-flow steps reverse sign: frequent reversals at
    the sampling scale signal even faster reversals (rent-and-return round trips) being aliased
    away. Report it to justify, or caution against, a chosen polling cadence in a study.

    Returns
    -------
    pandas.DataFrame
        ``system_id, station_id, high_frequency_loss_risk`` (the sign-reversal rate in ``[0, 1]``,
        ``NaN`` when there are too few moves) and ``n_intervals``.
    """
    flow = calculate_net_flow(panel).dropna(subset=["net_flow"])
    rows = []
    for (sid, stid), g in flow.groupby(["system_id", "station_id"], sort=False):
        nf = g["net_flow"].to_numpy()
        nonzero = nf[nf != 0]
        if len(nonzero) < 2:
            rate = np.nan
        else:
            signs = np.sign(nonzero)
            rate = float((signs[1:] != signs[:-1]).sum()) / (len(nonzero) - 1)
        rows.append(
            {
                "system_id": sid,
                "station_id": stid,
                "high_frequency_loss_risk": rate,
                "n_intervals": int(len(nf)),
            }
        )
    return pd.DataFrame(rows)


def docking_pressure(panel: pd.DataFrame) -> pd.DataFrame:
    """Per-observation docking saturation tension: typical inflow over free docks.

    A descriptive resilience indicator for return capacity. Each station's typical inflow (its
    mean positive net flow per poll) is divided by the docks free right now: a station that usually
    gains many bikes but has few open docks is under pressure to saturate. This describes the
    current tension; it does not forecast future demand.

    Returns
    -------
    pandas.DataFrame
        The :func:`calculate_net_flow` frame plus ``expected_inflow`` (mean positive net flow per
        station) and ``docking_pressure`` (= ``expected_inflow / num_docks_available``, ``NaN`` when
        no docks are free).
    """
    flow = calculate_net_flow(panel)
    require_columns(flow, ["num_docks_available"], what="docking_pressure")
    positives = flow["net_flow"].where(flow["net_flow"] > 0)
    expected = positives.groupby([flow["system_id"], flow["station_id"]]).transform("mean")
    docks = pd.to_numeric(flow["num_docks_available"], errors="coerce")
    flow["expected_inflow"] = expected.fillna(0.0)
    flow["docking_pressure"] = flow["expected_inflow"] / docks.where(docks > 0)
    return flow


def join_exogenous_timeseries(
    panel: pd.DataFrame,
    exogenous: pd.DataFrame,
    *,
    on_time: str = "fetched_at",
    exo_time: str | None = None,
    tolerance: str = "1h",
    direction: str = "nearest",
) -> pd.DataFrame:
    """Align an external time series (weather, traffic, air quality) onto the panel.

    Almost every cycling-usage study correlates demand with weather. Doing the time alignment by
    hand (unequal cadences, clock offsets, time zones) is a frequent source of methodological error.
    This wraps :func:`pandas.merge_asof` to attach each exogenous record to the nearest panel
    timestamp within ``tolerance``, safely. No network calls: bring your own exogenous frame.

    Both timestamp columns must share time-zone awareness (both tz-aware, ideally UTC, or both
    naive); convert first otherwise, since ``merge_asof`` will not mix them.

    Parameters
    ----------
    panel : pandas.DataFrame
        From :func:`build_availability_panel` or a flat frame with ``on_time``.
    exogenous : pandas.DataFrame
        External series with a timestamp column (``exo_time``, defaults to ``on_time``).
    tolerance : str, default "1h"
        Maximum gap to match across (a pandas offset alias).
    direction : {"nearest", "backward", "forward"}, default "nearest"
        Which neighbouring exogenous record to attach.

    Returns
    -------
    pandas.DataFrame
        The flattened panel with the exogenous columns merged in (unmatched rows carry ``NaN``).
    """
    df = _panel_frame(panel)
    exo_time = exo_time or on_time
    require_columns(df, [on_time], what="join_exogenous_timeseries")
    require_columns(exogenous, [exo_time], what="join_exogenous_timeseries(exogenous)")
    left = df.copy()
    right = exogenous.copy()
    left[on_time] = pd.to_datetime(left[on_time])
    right[exo_time] = pd.to_datetime(right[exo_time])
    left = left.sort_values(on_time)
    right = right.sort_values(exo_time)
    return pd.merge_asof(
        left,
        right,
        left_on=on_time,
        right_on=exo_time,
        tolerance=pd.Timedelta(tolerance),
        direction=direction,
    )


def station_outage_rates(panel: pd.DataFrame) -> pd.DataFrame:
    """Per-station fraction of time empty (stockout) and full (saturation).

    The most basic service-quality statistic, the kind reported as "station X is empty 24% of the
    time". A pure boolean count over the observed snapshots.

    Returns
    -------
    pandas.DataFrame
        ``system_id, station_id, stockout_rate, saturation_rate, n_obs`` (rates in ``[0, 1]``).
    """
    df = _panel_frame(panel)
    require_columns(
        df,
        ["system_id", "station_id", "num_bikes_available", "num_docks_available"],
        what="station_outage_rates",
    )
    bikes = pd.to_numeric(df["num_bikes_available"], errors="coerce")
    docks = pd.to_numeric(df["num_docks_available"], errors="coerce")
    work = pd.DataFrame(
        {
            "system_id": df["system_id"].to_numpy(),
            "station_id": df["station_id"].to_numpy(),
            "_empty": (bikes == 0).to_numpy(),
            "_full": (docks == 0).to_numpy(),
        }
    )
    return (
        work.groupby(["system_id", "station_id"])
        .agg(
            stockout_rate=("_empty", "mean"),
            saturation_rate=("_full", "mean"),
            n_obs=("_empty", "size"),
        )
        .reset_index()
    )


def flow_asymmetry_ratio(panel: pd.DataFrame, *, eps: float = 1e-9) -> pd.DataFrame:
    """Per-station ratio of total inflow to total outflow.

    A ratio near 1 is a self-balancing station; a ratio well below 1 (mostly departures) marks a
    morning-residential or hilltop station, and above 1 a sink. A compact descriptor of a station's
    structural role in the urban topography.

    Returns
    -------
    pandas.DataFrame
        ``system_id, station_id, inflow, outflow, asymmetry_ratio`` (= ``inflow / (outflow + eps)``).
    """
    flow = calculate_net_flow(panel).dropna(subset=["net_flow"])
    nf = flow["net_flow"]
    work = flow.assign(_in=nf.clip(lower=0), _out=(-nf).clip(lower=0))
    out = (
        work.groupby(["system_id", "station_id"])
        .agg(inflow=("_in", "sum"), outflow=("_out", "sum"))
        .reset_index()
    )
    out["asymmetry_ratio"] = out["inflow"] / (out["outflow"] + eps)
    return out


def fleet_turnover_proxy(panel: pd.DataFrame, *, freq: str = "1D") -> pd.DataFrame:
    """System-level turnover proxy: half the summed absolute flow per fleet vehicle, per period.

    The headline operational metric, "how many times is a vehicle used per day". Without trip (OD)
    data the summed absolute change in station availability is the best mathematical approximation
    of usage. It is a strict **lower bound**: by the aliasing argument in
    :func:`calculate_net_flow`, trips that cancel within a polling interval are invisible.

    Returns
    -------
    pandas.DataFrame
        ``system_id, period, activity, fleet_size, turnover_proxy`` (one row per system and period).
    """
    flow = calculate_net_flow(panel)
    require_columns(flow, ["num_bikes_available", "fetched_at"], what="fleet_turnover_proxy")
    flow = flow.assign(period=pd.to_datetime(flow["fetched_at"]).dt.floor(freq))
    activity = (
        flow.assign(_a=flow["net_flow"].abs()).groupby(["system_id", "period"])["_a"].sum().div(2.0)
    )
    bikes_per_snapshot = flow.groupby(["system_id", "period", "fetched_at"])[
        "num_bikes_available"
    ].sum()
    fleet = bikes_per_snapshot.groupby(level=["system_id", "period"]).max()
    out = pd.concat([activity.rename("activity"), fleet.rename("fleet_size")], axis=1).reset_index()
    out["turnover_proxy"] = out["activity"] / out["fleet_size"].where(out["fleet_size"] > 0)
    return out


def _gini(values: np.ndarray) -> float:
    """Gini coefficient of non-negative values (0 = even, 1 = concentrated)."""
    v = np.sort(np.asarray(values, dtype="float64"))
    v = v[np.isfinite(v)]
    n = v.size
    if n == 0 or v.sum() == 0:
        return float("nan")
    cum = np.cumsum(v)
    return float((n + 1 - 2 * np.sum(cum) / cum[-1]) / n)


def availability_synchrony(
    panel: pd.DataFrame,
    *,
    value_col: str = "num_bikes_available",
    freq: str = "1h",
    method: str = "pearson",
    min_overlap: int = 24,
    threshold: float | None = None,
) -> pd.DataFrame:
    """Pairwise correlation of station availability series: a functional synchrony network.

    Resamples each station to ``freq`` and correlates every pair over their common support
    (requiring ``min_overlap`` shared observations), returning the upper-triangle **edge list**.
    This is the descriptive adjacency that precedes community detection of co-fluctuating stations.
    It correlates observed availability only; it infers no trips and no direction (no OD). Bring
    your own graph library (NetworkX, igraph) for the network analysis itself.

    Parameters
    ----------
    panel : pandas.DataFrame
        From :func:`build_availability_panel` or a flat frame with ``station_id, fetched_at`` and
        ``value_col``.
    freq : str, default "1h"
        Resampling bin for the per-station series.
    method : {"pearson", "spearman", "kendall"}, default "pearson"
        Correlation method.
    min_overlap : int, default 24
        Minimum shared observations for a pair to be reported.
    threshold : float, optional
        If given, keep only edges with ``abs(corr) >= threshold``.

    Returns
    -------
    pandas.DataFrame
        ``station_a, station_b, corr, n_overlap`` (upper triangle, unmatched pairs dropped).

    References
    ----------
    O'Brien, Cheshire and Batty (2014); the functional-connectivity correlation-network idiom.
    """
    df = _panel_frame(panel)
    require_columns(df, ["station_id", "fetched_at", value_col], what="availability_synchrony")
    wide = pd.DataFrame(
        {
            "_t": pd.to_datetime(df["fetched_at"]).dt.floor(freq).to_numpy(),
            "station_id": df["station_id"].to_numpy(),
            "_v": pd.to_numeric(df[value_col], errors="coerce").to_numpy(),
        }
    )
    mat = wide.pivot_table(index="_t", columns="station_id", values="_v", aggfunc="mean")
    cols = mat.columns.to_numpy()
    if cols.size < 2:
        return pd.DataFrame(columns=["station_a", "station_b", "corr", "n_overlap"])
    corr = mat.corr(method=method, min_periods=min_overlap).to_numpy()
    present = mat.notna().astype("int64")
    n_overlap = present.T.to_numpy() @ present.to_numpy()
    ii, jj = np.triu_indices(cols.size, k=1)
    edges = pd.DataFrame(
        {
            "station_a": cols[ii],
            "station_b": cols[jj],
            "corr": corr[ii, jj],
            "n_overlap": n_overlap[ii, jj],
        }
    ).dropna(subset=["corr"])
    if threshold is not None:
        edges = edges[edges["corr"].abs() >= threshold]
    return edges.reset_index(drop=True)


def outage_survival(episodes: pd.DataFrame, *, by: str | None = None) -> pd.DataFrame:
    """Empirical survival function of outage durations: the time-to-recovery view.

    From the :func:`stockout_episodes` event table, the empirical survival
    :math:`S(t) = \\Pr(\\text{duration} > t)` of outage durations, optionally grouped, with the
    median and P90 time-to-recovery. Strictly empirical (Kaplan-Meier reduces to the ECDF without
    censoring). Episodes still open at the observation window's edge are right-censored in the data;
    they are not imputed, so read the longest durations as lower bounds.

    Parameters
    ----------
    episodes : pandas.DataFrame
        Output of :func:`stockout_episodes` (needs ``duration_minutes``).
    by : str, optional
        A grouping column (e.g. ``"station_id"`` or ``"kind"``); one survival curve per group.

    Returns
    -------
    pandas.DataFrame
        ``[<by>,] duration_minutes, survival, at_risk, n_episodes, median_recovery, p90_recovery``.

    References
    ----------
    Kaplan and Meier (1958), used here as a descriptive empirical survival estimator.
    """
    require_columns(episodes, ["duration_minutes"], what="outage_survival")

    def _curve(group: pd.DataFrame) -> pd.DataFrame:
        d = np.sort(pd.to_numeric(group["duration_minutes"], errors="coerce").dropna().to_numpy())
        if d.size == 0:
            return pd.DataFrame(
                columns=[
                    "duration_minutes",
                    "survival",
                    "at_risk",
                    "n_episodes",
                    "median_recovery",
                    "p90_recovery",
                ]
            )
        uniq = np.unique(d)
        return pd.DataFrame(
            {
                "duration_minutes": uniq,
                "survival": [float((d > t).mean()) for t in uniq],
                "at_risk": [int((d >= t).sum()) for t in uniq],
                "n_episodes": int(d.size),
                "median_recovery": float(np.median(d)),
                "p90_recovery": float(np.quantile(d, 0.9)),
            }
        )

    if by is None:
        return _curve(episodes).reset_index(drop=True)
    parts = []
    for value, group in episodes.groupby(by, sort=True):
        curve = _curve(group)
        curve.insert(0, by, value)
        parts.append(curve)
    if not parts:
        return _curve(episodes.iloc[:0])
    return pd.concat(parts, ignore_index=True)


def temporal_concentration(panel: pd.DataFrame, *, freq: str = "1h") -> pd.DataFrame:
    """Per-station temporal peaking: the Gini of activity across time-of-day bins.

    Distributes each station's activity (turnover :math:`\\sum|\\Delta|`) across the day's ``freq``
    bins and takes the Gini of that distribution: ``1`` means all activity in one peak bin, ``0``
    means uniform. The temporal analogue of the spatial :func:`dynamic_gini_index`, for sizing
    peak-hour infrastructure and rebalancing windows. Convert to local time first for local hours.

    Returns
    -------
    pandas.DataFrame
        ``system_id, station_id, temporal_gini, peak_share, peak_bin`` (``peak_bin`` is minutes
        since midnight of the busiest bin).
    """
    flow = calculate_net_flow(panel).dropna(subset=["net_flow"])
    if flow.empty:
        return pd.DataFrame(
            columns=["system_id", "station_id", "temporal_gini", "peak_share", "peak_bin"]
        )
    step_min = pd.tseries.frequencies.to_offset(freq).nanos / 6e10
    ts = pd.to_datetime(flow["fetched_at"])
    minutes = ts.dt.hour * 60 + ts.dt.minute + ts.dt.second / 60
    tod = (np.floor(minutes / step_min) * step_min).astype("int64")
    by_bin = (
        flow.assign(activity=flow["net_flow"].abs(), _tod=tod.to_numpy())
        .groupby(["system_id", "station_id", "_tod"])["activity"]
        .sum()
    )
    rows = []
    for (sysid, stid), series in by_bin.groupby(level=["system_id", "station_id"]):
        vals = series.to_numpy()
        total = vals.sum()
        bins = series.index.get_level_values("_tod").to_numpy()
        rows.append(
            {
                "system_id": sysid,
                "station_id": stid,
                "temporal_gini": _gini(vals),
                "peak_share": float(vals.max() / total) if total > 0 else np.nan,
                "peak_bin": int(bins[np.argmax(vals)]) if total > 0 else -1,
            }
        )
    return pd.DataFrame(rows)

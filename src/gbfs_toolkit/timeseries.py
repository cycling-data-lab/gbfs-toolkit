"""Longitudinal layer — turn a stream of snapshots into a research data lake.

The library owns the *formatting, deduplication and I/O*; your orchestrator (cron /
Airflow / Dagster) owns the polling loop. Requires the optional ``[parquet]`` extra
(``pyarrow``).

Workflow
--------
1. A poller calls :func:`append_to_parquet` on each fetched snapshot — fast, append-only,
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

    - ``columns`` — project only the columns you need (the keys ``system_id``,
      ``station_id``, ``fetched_at`` and, when de-duplicating, ``last_reported`` are always
      read). Fewer columns ⇒ less I/O and RAM.
    - ``filters`` — an extra ``pyarrow.dataset`` predicate ANDed with the built-in
      system/date filter, applied *before* materialising (row-group pruning). Build it with
      ``import pyarrow.dataset as ds; ds.field("num_bikes_available") == 0``.

    Local time
    ----------
    Pass ``target_tz`` (e.g. ``"America/Los_Angeles"``) to convert ``fetched_at`` /
    ``last_reported`` to that zone **before** any dedup or resample. Resampling tz-aware UTC
    data would otherwise cut "days" at UTC midnight — i.e. mid-afternoon local time —
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

    Adds ``net_flow`` — the Δ in ``num_bikes_available`` vs the previous poll of the same
    station. ``net_flow`` is ``NaN`` across polls where ``last_reported`` did not change (the
    feed re-served an identical observation), so you don't read spurious zero-flows.

    This intentionally reports the **observed flow only**, not its cause. Attributing a flow to
    rebalancing vs. organic demand is not identifiable from availability counts alone — a
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
    """Discrete empty/full episodes per station — the service-quality view of a panel.

    Where :func:`coverage_report` and ``availability_stats`` give *fractions* of time, this
    returns the individual outage **events**: each contiguous run of empty (no bikes) or full
    (no docks) snapshots becomes one row, so you can study how *often* stockouts happen and how
    *long* they last. Durations span the observed snapshots in the run (a single-observation
    episode has duration 0) — read them together with :func:`coverage_report`.

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


def turnover(panel: pd.DataFrame, *, freq: str = "1D") -> pd.DataFrame:
    """Per-station activity proxy — summed absolute net flow per period.

    A cheap, model-free measure of how busy a station is. It is a **lower bound**: by the
    aliasing argument in :func:`calculate_net_flow`, trips that cancel within a polling interval
    are invisible. Use it for relative comparison (which stations / days are busier), not as a
    trip count.

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
    return out


def coverage_report(panel: pd.DataFrame, *, expected_freq: str = "5min") -> pd.DataFrame:
    """Per-station longitudinal coverage — quantify missingness *before* you model.

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
    """A cryptographic manifest of a Parquet lake — for citable, reproducible datasets.

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
    except Exception:  # noqa: BLE001 — summary is best-effort; the hashes are the point
        pass
    return manifest

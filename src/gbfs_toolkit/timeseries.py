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

import uuid
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


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

    Accepts a panel from :func:`build_availability_panel` (MultiIndexed) or a flat frame;
    returns a flat frame with ``system_id, station_id, fetched_at`` columns.
    """
    df = panel.reset_index() if isinstance(panel.index, pd.MultiIndex) else panel.copy()
    df = df.sort_values(["system_id", "station_id", "fetched_at"])
    grp = df.groupby(["system_id", "station_id"], sort=False)

    df["net_flow"] = grp["num_bikes_available"].diff()
    if "last_reported" in df:
        unchanged = grp["last_reported"].diff().eq(pd.Timedelta(0))
        df.loc[unchanged, "net_flow"] = np.nan
    return df.reset_index(drop=True)

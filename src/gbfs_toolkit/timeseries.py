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
) -> pd.DataFrame:
    """Read a partitioned dataset into a tidy availability panel.

    Filters by ``system_id`` and the ``date`` partition *before* loading (memory-bounded),
    then de-duplicates redundant polls (same ``station_id`` + ``last_reported``) and
    optionally resamples each station to a fixed frequency (forward-filled).

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

    df = dataset.to_table(filter=filt).to_pandas()
    if df.empty:
        return df

    df["fetched_at"] = pd.to_datetime(df["fetched_at"], utc=True)
    if "last_reported" in df:
        df["last_reported"] = pd.to_datetime(df["last_reported"], utc=True)
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


def calculate_net_flow(
    panel: pd.DataFrame,
    *,
    rebalancing_threshold: int = 3,
    account_for_system: bool = False,
) -> pd.DataFrame:
    """Period-over-period change in available bikes per station.

    Adds ``net_flow`` (Δ ``num_bikes_available`` vs the previous poll of the same station).
    ``net_flow`` is ``NaN`` across polls where ``last_reported`` did not change (the feed
    re-served an identical observation), so you don't read spurious zero-flows.

    Rebalancing heuristic
    ---------------------
    By default ``is_rebalancing_suspected`` is the *naive* test ``|net_flow| >
    rebalancing_threshold``. This conflates a rebalancing van with a burst of organic
    demand (e.g. a train disgorging riders), so treat it as a coarse screen.

    With ``account_for_system=True`` the function also computes the **system-wide**
    available-bike total per timestamp and its change (``system_net_flow``), and a station
    spike is flagged only when it is *corroborated* by a same-sign system-level change of
    comparable size — i.e. the system's mass actually changed (a van injected or removed
    bikes). This reliably catches fleet injection/removal; it cannot, at panel resolution,
    distinguish an *internal* van move (A→B, system flat) from organic demand — those stay
    unflagged. Use it when you have full-system coverage in the panel.

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

    big = df["net_flow"].abs() > rebalancing_threshold
    if account_for_system:
        totals = (
            df.groupby(["system_id", "fetched_at"])["num_bikes_available"]
            .sum()
            .rename("system_total")
            .reset_index()
            .sort_values(["system_id", "fetched_at"])
        )
        totals["system_net_flow"] = totals.groupby("system_id")["system_total"].diff()
        df = df.merge(
            totals[["system_id", "fetched_at", "system_net_flow"]],
            on=["system_id", "fetched_at"],
            how="left",
        )
        corroborated = (np.sign(df["net_flow"]) == np.sign(df["system_net_flow"])) & (
            df["system_net_flow"].abs() >= rebalancing_threshold
        )
        df["is_rebalancing_suspected"] = big & corroborated.fillna(False)
    else:
        df["is_rebalancing_suspected"] = big
    return df.reset_index(drop=True)

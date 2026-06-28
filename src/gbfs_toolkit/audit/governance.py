"""Feed governance audit: characterise the privacy policy a feed implements.

A GBFS feed may rotate ``vehicle_id`` after every trip (the spec's privacy guidance,
2.1+) or keep it stable. This is not a metric of the *system* but of the *feed*: it
tells a researcher whether origin-destination work is even identifiable (the
persistence ``q`` is the fundamental bound on spatio-temporal identifiability) and,
in plain terms, whether the operator follows the privacy recommendation. Strictly
descriptive: it measures the published identifiers, it never reconstructs a trip.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from gbfs_toolkit.core.models import require_columns
from gbfs_toolkit.core.utils import panel_frame


def _mean_jaccard(sets: pd.Series, lag: pd.Timedelta) -> float:
    """Mean Jaccard similarity of the id-set ``lag`` apart, matched to the nearest snapshot."""
    times = pd.DatetimeIndex(sets.index)
    tol = lag / 2
    vals: list[float] = []
    for t in times:
        pos = times.get_indexer([t + lag], method="nearest")[0]
        if pos < 0:
            continue
        nt = times[pos]
        if nt == t or abs(nt - (t + lag)) > tol:
            continue
        a, b = sets.loc[t], sets.loc[nt]
        union = len(a | b)
        if union:
            vals.append(len(a & b) / union)
    return float(np.mean(vals)) if vals else float("nan")


def vehicle_id_persistence(
    vehicle_panel: pd.DataFrame,
    *,
    lags: tuple[str, ...] = ("1h", "12h", "24h"),
    time_col: str = "fetched_at",
    id_col: str = "vehicle_id",
) -> pd.DataFrame:
    """Characterise whether a feed rotates or persists its ``vehicle_id`` values.

    Two purely empirical statistics per system (no survival model): the **rolling
    Jaccard** overlap of the live id-set ``lag`` apart, and the **observed lifespan**
    (last minus first sighting) of each id. A feed that rotates ids hourly drives
    ``jaccard_24h`` toward 0 and the median lifespan toward the polling step; a feed
    that keeps ids stable keeps both high. The inverse of this persistence is the
    ceiling on origin-destination identifiability, so this is the check that tells a
    study whether trip-level analysis is even admissible.

    Parameters
    ----------
    vehicle_panel : pandas.DataFrame
        Long frame of free-floating vehicle snapshots with ``vehicle_id`` and
        ``fetched_at`` (and ``system_id`` if multiple systems are stacked).
    lags : tuple of str, default ("1h", "12h", "24h")
        Offsets (pandas aliases) at which to compute the id-set Jaccard overlap.
    time_col, id_col : str
        Snapshot-time and vehicle-id column names.

    Returns
    -------
    pandas.DataFrame
        One row per ``system_id``: ``n_snapshots``, ``n_unique_ids``,
        ``median_lifespan_h``, ``p90_lifespan_h`` and one ``jaccard_<lag>`` column per
        lag. Low Jaccard and a short lifespan are the signature of a rotating feed.

    See Also
    --------
    [`detect_ghost_vehicles`][gbfs_toolkit.detect_ghost_vehicles] : Track individual units, which needs stable ids.
    [`vehicle_idle_time`][gbfs_toolkit.vehicle_idle_time] : The idle-share series, also id-dependent.
    [`reconcile_fleet_state`][gbfs_toolkit.reconcile_fleet_state] : The deduplicated fleet tally.

    Examples
    --------
    A feed that replaces every id between snapshots has zero one-step overlap:

    >>> import pandas as pd
    >>> panel = pd.DataFrame({
    ...     "vehicle_id": ["a0", "a1", "b0", "b1", "c0", "c1"],
    ...     "fetched_at": pd.to_datetime(
    ...         ["2026-01-01T00:00Z"] * 2 + ["2026-01-01T01:00Z"] * 2
    ...         + ["2026-01-01T02:00Z"] * 2),
    ... })
    >>> float(vehicle_id_persistence(panel, lags=("1h",))["jaccard_1h"].iloc[0])
    0.0
    """
    df = panel_frame(vehicle_panel)
    require_columns(df, [id_col, time_col], what="vehicle_id_persistence")
    cols = [c for c in ["system_id", id_col, time_col] if c in df.columns]
    df = df[cols].copy()
    df[time_col] = pd.to_datetime(df[time_col], utc=True)
    if "system_id" not in df.columns:
        df["system_id"] = "system"

    rows = []
    for sid, g in df.groupby("system_id", sort=False):
        sets = g.groupby(time_col)[id_col].agg(set).sort_index()
        span_h = g.groupby(id_col)[time_col].agg(
            lambda s: (s.max() - s.min()).total_seconds() / 3600.0
        )
        row: dict = {
            "system_id": sid,
            "n_snapshots": int(len(sets)),
            "n_unique_ids": int(g[id_col].nunique()),
            "median_lifespan_h": round(float(span_h.median()), 2) if len(span_h) else float("nan"),
            "p90_lifespan_h": round(float(span_h.quantile(0.9)), 2)
            if len(span_h)
            else float("nan"),
        }
        for lag in lags:
            row[f"jaccard_{lag}"] = round(_mean_jaccard(sets, pd.Timedelta(lag)), 4)
        rows.append(row)
    return pd.DataFrame(rows)

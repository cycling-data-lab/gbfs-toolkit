"""Descriptive statistics — readable summaries of canonical frames.

The plumbing (ingest / audit / panel) turns feeds into tidy data; this module turns tidy
data into the numbers a researcher actually reports. Strictly **descriptive** — no OD/trip
inference, no prediction (those belong in dedicated research code). All functions are pure
and pandas-only.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from gbfs_toolkit.analysis import STATION_STATES, station_state


def _num(df: pd.DataFrame, col: str) -> pd.Series:
    """Numeric view of a column (NaN where absent/unparseable)."""
    if col not in df.columns:
        return pd.Series(np.nan, index=df.index, dtype="float64")
    return pd.to_numeric(df[col], errors="coerce")


def system_profile(availability: pd.DataFrame) -> pd.Series:
    """A one-glance numeric profile of one availability snapshot — the bikeshare ``describe()``.

    Parameters
    ----------
    availability : pandas.DataFrame
        An availability frame (e.g. from :func:`~gbfs_toolkit.join_availability`): needs
        ``num_bikes_available`` / ``num_docks_available``; uses ``capacity``, ``station_type``,
        ``is_virtual_station``, ``is_renting`` / ``is_returning``, ``fetched_at`` /
        ``last_reported`` when present.

    Returns
    -------
    pandas.Series
        Counts and rates: ``n_stations``, ``total_capacity``, ``total_bikes_available``,
        ``total_docks_available``, ``mean_occupancy``, ``pct_<state>`` for each
        :data:`~gbfs_toolkit.analysis.STATION_STATES`, and ``staleness_min_median``.
    """
    df = availability
    bikes, docks = _num(df, "num_bikes_available"), _num(df, "num_docks_available")
    out: dict[str, float] = {"n_stations": int(len(df))}
    if "capacity" in df.columns:
        out["total_capacity"] = float(_num(df, "capacity").sum())
    out["total_bikes_available"] = float(bikes.sum())
    out["total_docks_available"] = float(docks.sum())

    denom = bikes + docks
    occ = (bikes / denom).where(denom > 0)
    out["mean_occupancy"] = round(float(occ.mean()), 4) if occ.notna().any() else float("nan")

    if len(df):
        states = station_state(df).value_counts(normalize=True)
        for s in STATION_STATES:
            out[f"pct_{s}"] = round(float(states.get(s, 0.0)), 4)

    if "fetched_at" in df.columns and "last_reported" in df.columns:
        lag = (
            pd.to_datetime(df["fetched_at"], utc=True)
            - pd.to_datetime(df["last_reported"], utc=True)
        ).dt.total_seconds() / 60
        if lag.notna().any():
            out["staleness_min_median"] = round(float(lag.median()), 1)
    return pd.Series(out)


def compare_systems(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Stack :func:`system_profile` across many systems into a comparison table.

    Parameters
    ----------
    frames : dict of str -> pandas.DataFrame
        ``{system_id: availability_frame}`` (e.g. built from
        :func:`~gbfs_toolkit.fetch_multiple`).

    Returns
    -------
    pandas.DataFrame
        One row per system (index ``system_id``), one column per profile metric.
    """
    rows = {sid: system_profile(av) for sid, av in frames.items()}
    out = pd.DataFrame(rows).T
    out.index.name = "system_id"
    return out


def _gini(x: np.ndarray) -> float:
    """Gini coefficient of a non-negative array (0 = equal, →1 = concentrated)."""
    x = np.sort(x)
    n = x.size
    total = x.sum()
    if n == 0 or total == 0:
        return float("nan")
    idx = np.arange(1, n + 1)
    return float((2 * np.sum(idx * x)) / (n * total) - (n + 1) / n)


def concentration_metrics(info: pd.DataFrame, *, value_col: str = "capacity") -> pd.Series:
    """How concentrated is capacity across stations? — an equity / coverage lens.

    Reports the **Gini coefficient** of ``value_col`` and the share held by the top decile of
    stations (a system can claim wide coverage yet stash most bikes in a few central hubs).
    Deliberately *outside* the published A1–A7 audit taxonomy — this is a descriptive metric,
    not a feed-quality verdict.

    Returns
    -------
    pandas.Series
        ``n_stations``, ``total_capacity``, ``gini``, ``top_decile_share``.
    """
    x = _num(info, value_col).dropna().to_numpy()
    x = np.sort(x[x > 0])
    out: dict[str, float] = {"n_stations": int(x.size)}
    if x.size == 0:
        out["total_capacity"] = 0.0
        out["gini"] = float("nan")
        out["top_decile_share"] = float("nan")
        return pd.Series(out)
    out["total_capacity"] = float(x.sum())
    out["gini"] = round(_gini(x), 4)
    k = max(1, int(np.ceil(0.1 * x.size)))
    out["top_decile_share"] = round(float(x[-k:].sum() / x.sum()), 4)
    return pd.Series(out)


def availability_stats(panel: pd.DataFrame, *, time_col: str = "fetched_at") -> pd.DataFrame:
    """Per-station longitudinal statistics from an availability panel.

    Complements :func:`~gbfs_toolkit.diurnal_profiles` (which yields the curves) with
    comparable scalars per station: central tendency, time spent empty/full, volatility, and
    the diurnal amplitude / peak hour of occupancy.

    Parameters
    ----------
    panel : pandas.DataFrame
        A panel from :func:`~gbfs_toolkit.build_availability_panel` (MultiIndexed) or a flat
        frame with ``system_id, station_id, num_bikes_available, num_docks_available`` and a
        time column. Hour-of-day uses ``time_col`` **as stored** — pass a panel built with
        ``target_tz`` for local-time peaks.

    Returns
    -------
    pandas.DataFrame
        Indexed by ``(system_id, station_id)``: ``n_obs``, ``mean_bikes``, ``median_bikes``,
        ``occupancy_mean``, ``pct_time_empty``, ``pct_time_full``, ``volatility``,
        ``diurnal_amplitude``, ``peak_hour``.
    """
    df = panel.reset_index() if isinstance(panel.index, pd.MultiIndex) else panel.copy()
    bikes, docks = _num(df, "num_bikes_available"), _num(df, "num_docks_available")
    denom = bikes + docks
    work = pd.DataFrame(
        {
            "system_id": df["system_id"],
            "station_id": df["station_id"],
            "bikes": bikes,
            "occ": (bikes / denom).where(denom > 0),
            "empty": bikes <= 0,
            "full": docks <= 0,
            "hour": pd.to_datetime(df[time_col]).dt.hour,
        }
    )
    g = work.groupby(["system_id", "station_id"], sort=False)
    res = pd.DataFrame(
        {
            "n_obs": g.size(),
            "mean_bikes": g["bikes"].mean(),
            "median_bikes": g["bikes"].median(),
            "occupancy_mean": g["occ"].mean(),
            "pct_time_empty": g["empty"].mean(),
            "pct_time_full": g["full"].mean(),
            "volatility": g["bikes"].std(),
        }
    )

    hourly = work.groupby(["system_id", "station_id", "hour"])["occ"].mean().dropna()
    if len(hourly):
        by_station = hourly.groupby(level=[0, 1])
        res["diurnal_amplitude"] = by_station.max() - by_station.min()
        res["peak_hour"] = by_station.idxmax().map(lambda t: t[2])
    else:
        res["diurnal_amplitude"] = np.nan
        res["peak_hour"] = np.nan
    return res

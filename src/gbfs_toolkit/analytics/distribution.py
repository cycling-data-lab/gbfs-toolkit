"""Inequality and system profiles: concentration, Lorenz/Gini/Theil, dynamic equity.

Strictly **descriptive** summaries of canonical frames: no OD/trip inference, no prediction.
All functions are pure and pandas-only. Exposed on the ``.gbfs`` accessor.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from gbfs_toolkit.analytics.frames import STATION_STATES, station_state
from gbfs_toolkit.core.models import require_columns
from gbfs_toolkit.core.utils import gini, num


def system_profile(availability: pd.DataFrame) -> pd.Series:
    """A one-glance numeric profile of one availability snapshot: the bikeshare ``describe()``.

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
        :data:`~gbfs_toolkit.analytics.frames.STATION_STATES`, and ``staleness_min_median``.
    """
    df = availability
    bikes, docks = num(df, "num_bikes_available"), num(df, "num_docks_available")
    out: dict[str, float] = {"n_stations": int(len(df))}
    if "capacity" in df.columns:
        out["total_capacity"] = float(num(df, "capacity").sum())
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


def _theil(x: np.ndarray) -> float:
    """Theil T index of a positive array (0 = equal; decomposable alternative to Gini)."""
    mu = x.mean()
    if mu == 0:
        return float("nan")
    r = x / mu
    return float(np.mean(r * np.log(r)))


def concentration_metrics(info: pd.DataFrame, *, value_col: str = "capacity") -> pd.Series:
    """How concentrated is capacity across stations? An equity / coverage lens.

    Reports the **Gini coefficient** and **Theil T index** of ``value_col`` and the share held
    by the top decile of stations (a system can claim wide coverage yet stash most bikes in a
    few central hubs). Deliberately *outside* the published A1–A7 audit taxonomy; these are
    descriptive metrics, not a feed-quality verdict. See :func:`lorenz_curve` for the curve.

    Returns
    -------
    pandas.Series
        ``n_stations``, ``total_capacity``, ``gini``, ``theil``, ``top_decile_share``.
    """
    x = num(info, value_col).dropna().to_numpy()
    x = np.sort(x[x > 0])
    out: dict[str, float] = {"n_stations": int(x.size)}
    if x.size == 0:
        out["total_capacity"] = 0.0
        out["gini"] = float("nan")
        out["theil"] = float("nan")
        out["top_decile_share"] = float("nan")
        return pd.Series(out)
    out["total_capacity"] = float(x.sum())
    out["gini"] = round(gini(x), 4)
    out["theil"] = round(_theil(x), 4)
    k = max(1, int(np.ceil(0.1 * x.size)))
    out["top_decile_share"] = round(float(x[-k:].sum() / x.sum()), 4)
    return pd.Series(out)


def lorenz_curve(info: pd.DataFrame, *, value_col: str = "capacity") -> pd.DataFrame:
    """Lorenz-curve points for plotting capacity inequality.

    Returns the cumulative share of stations vs. cumulative share of ``value_col``, starting
    at the origin ``(0, 0)``. The diagonal is perfect equality; the area between it and the
    curve is half the Gini. Pairs with :func:`concentration_metrics`.

    Returns
    -------
    pandas.DataFrame
        ``cum_population_share``, ``cum_value_share`` (both in ``[0, 1]``, ascending).
    """
    x = num(info, value_col).dropna().to_numpy()
    x = np.sort(x[x > 0])
    if x.size == 0:
        return pd.DataFrame({"cum_population_share": [0.0], "cum_value_share": [0.0]})
    cum_pop = np.arange(1, x.size + 1) / x.size
    cum_val = np.cumsum(x) / x.sum()
    return pd.DataFrame(
        {
            "cum_population_share": np.concatenate([[0.0], cum_pop]),
            "cum_value_share": np.concatenate([[0.0], cum_val]),
        }
    )


def dynamic_gini_index(
    panel: pd.DataFrame, *, target_col: str = "num_bikes_available", time_col: str = "fetched_at"
) -> pd.DataFrame:
    """Gini coefficient of available bikes across stations, as a time series.

    Capacity-based concentration (see :func:`concentration_metrics`) measures a network's static
    design. This measures the *dynamic* inequality of where the bikes actually are: a system with
    evenly distributed capacity can still become deeply unequal at 18:00, when the fleet piles into
    one district. A rising curve over the day objectifies that loss of equity.

    Parameters
    ----------
    panel : pandas.DataFrame
        From :func:`build_availability_panel` or a flat frame with ``station_id``, ``time_col`` and
        ``target_col``.
    target_col : str, default "num_bikes_available"
        The per-station quantity whose distribution is measured.
    time_col : str, default "fetched_at"
        Snapshot timestamp.

    Returns
    -------
    pandas.DataFrame
        ``<time_col>, gini, n_stations`` (one row per snapshot).
    """
    df = panel.reset_index() if isinstance(panel.index, pd.MultiIndex) else panel.copy()
    require_columns(df, [time_col, target_col], what="dynamic_gini_index")
    vals = pd.to_numeric(df[target_col], errors="coerce")
    rows = []
    for t, idx in df.groupby(time_col, sort=True).groups.items():
        v = vals.loc[idx].dropna().to_numpy()
        rows.append({time_col: t, "gini": gini(v), "n_stations": int(v.size)})
    return pd.DataFrame(rows)

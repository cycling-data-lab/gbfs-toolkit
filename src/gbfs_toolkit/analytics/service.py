"""Level of service and equity of access: reliability, outages, recovery, docking pressure.

Publication-ready descriptive service-quality metrics computed from the canonical panel.
Strictly descriptive (no OD, prediction or imputation), exposed on the ``.gbfs`` accessor.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from gbfs_toolkit.core.models import require_columns
from gbfs_toolkit.core.utils import panel_frame
from gbfs_toolkit.io.timeseries import calculate_net_flow


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
    df = panel_frame(panel)
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


def station_outage_rates(panel: pd.DataFrame) -> pd.DataFrame:
    """Per-station fraction of time empty (stockout) and full (saturation).

    The most basic service-quality statistic, the kind reported as "station X is empty 24% of the
    time". A pure boolean count over the observed snapshots.

    Returns
    -------
    pandas.DataFrame
        ``system_id, station_id, stockout_rate, saturation_rate, n_obs`` (rates in ``[0, 1]``).
    """
    df = panel_frame(panel)
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


def capacity_utilization(panel: pd.DataFrame, info: pd.DataFrame) -> pd.DataFrame:
    """Add ``utilization_rate`` = available bikes / station capacity.

    Normalising by capacity makes stations and whole networks comparable: ten bikes in a 15-dock
    station (67%) is not ten bikes in a 40-dock station (25%). This is the standard step before a
    cross-city ANOVA or regression. Virtual or zero-capacity stations yield ``pd.NA`` rather than a
    divide-by-zero.

    Parameters
    ----------
    panel : pandas.DataFrame
        Panel or snapshot with ``station_id`` and ``num_bikes_available`` (and ``capacity`` if
        already present).
    info : pandas.DataFrame
        Canonical station inventory providing ``capacity`` (joined on the shared id columns) when
        ``panel`` does not already carry it.

    Returns
    -------
    pandas.DataFrame
        A copy of ``panel`` with a nullable ``utilization_rate`` column in ``[0, 1]``.
    """
    out = panel_frame(panel)
    require_columns(out, ["station_id", "num_bikes_available"], what="capacity_utilization")
    if "capacity" not in out.columns:
        require_columns(info, ["station_id", "capacity"], what="capacity_utilization(info)")
        keys = [k for k in ("system_id", "station_id") if k in out.columns and k in info.columns]
        out = out.merge(info[[*keys, "capacity"]].drop_duplicates(keys), on=keys, how="left")
    cap = pd.to_numeric(out["capacity"], errors="coerce")
    bikes = pd.to_numeric(out["num_bikes_available"], errors="coerce")
    out["utilization_rate"] = (bikes / cap.where(cap > 0)).astype("Float64")
    return out

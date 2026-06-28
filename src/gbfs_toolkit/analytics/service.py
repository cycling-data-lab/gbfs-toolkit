"""Level of service and equity of access: reliability, outages, recovery, docking pressure.

Publication-ready descriptive service-quality metrics computed from the canonical panel.
Strictly descriptive (no OD, prediction or imputation), exposed on the ``.gbfs`` accessor.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from gbfs_toolkit.core.models import require_columns
from gbfs_toolkit.core.utils import num, panel_frame, time_of_day_minutes
from gbfs_toolkit.io.timeseries import calculate_net_flow


def censored_time_ratio(
    panel: pd.DataFrame,
    *,
    bikes_col: str = "num_bikes_available",
    docks_col: str = "num_docks_available",
) -> pd.Series:
    """Fraction of station-time at a saturation boundary, where demand is unobservable.

    When a station is empty (0 bikes) a would-be rider leaves no trace; when it is
    full (0 docks) a would-be returner leaves no trace. This reports the share of
    station-time in each censored state, and their union, as a measure of how much of
    the system's demand signal is *lost to observation*. It is strictly descriptive:
    it quantifies the observability gap and never infers the missing flows (that would
    be latent-demand imputation, out of scope).

    Returns
    -------
    pandas.Series
        ``{empty_ratio, full_ratio, censored_ratio}`` where ``censored_ratio`` is the
        union (empty or full).

    See Also
    --------
    [`station_outage_rates`][gbfs_toolkit.station_outage_rates] : Per-station empty/full rates.
    [`service_reliability_index`][gbfs_toolkit.service_reliability_index] : Level-of-service probabilities.

    Examples
    --------
    >>> import pandas as pd
    >>> panel = pd.DataFrame({
    ...     "num_bikes_available": [0, 5, 5, 10],
    ...     "num_docks_available": [10, 0, 5, 5],
    ... })
    >>> float(censored_time_ratio(panel)["censored_ratio"])
    0.5
    """
    require_columns(panel, [bikes_col, docks_col], what="censored_time_ratio")
    bikes = num(panel, bikes_col)
    docks = num(panel, docks_col)
    valid = bikes.notna() & docks.notna()
    if not valid.any():
        return pd.Series(
            {
                "empty_ratio": float("nan"),
                "full_ratio": float("nan"),
                "censored_ratio": float("nan"),
            }
        )
    empty = bikes[valid] <= 0
    full = docks[valid] <= 0
    return pd.Series(
        {
            "empty_ratio": float(empty.mean()),
            "full_ratio": float(full.mean()),
            "censored_ratio": float((empty | full).mean()),
        }
    )


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
        From [`build_availability_panel`][gbfs_toolkit.build_availability_panel] (MultiIndexed) or a flat frame with
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

    See Also
    --------
    [`station_outage_rates`][gbfs_toolkit.station_outage_rates] : Time-share empty/full per station.
    [`censored_time_ratio`][gbfs_toolkit.censored_time_ratio] : Share of demand lost to saturation.
    [`capacity_utilization`][gbfs_toolkit.capacity_utilization] : Normalise availability by capacity first.

    Examples
    --------
    >>> import pandas as pd
    >>> panel = pd.DataFrame({
    ...     "system_id": "s", "station_id": "a",
    ...     "fetched_at": pd.to_datetime(["2026-01-01T08:00Z", "2026-01-08T08:00Z"]),
    ...     "num_bikes_available": [5, 0], "num_docks_available": [5, 10],
    ... })
    >>> float(service_reliability_index(panel)["prob_bikes_avail"].iloc[0])
    0.5
    """
    df = panel_frame(panel)
    require_columns(
        df,
        ["system_id", "station_id", "fetched_at", "num_bikes_available", "num_docks_available"],
        what="service_reliability_index",
    )
    bucket = time_of_day_minutes(df["fetched_at"], freq)
    bikes_ok = pd.to_numeric(df["num_bikes_available"], errors="coerce") >= min_bikes
    docks_ok = pd.to_numeric(df["num_docks_available"], errors="coerce") >= min_docks
    work = pd.DataFrame(
        {
            "system_id": df["system_id"].to_numpy(),
            "station_id": df["station_id"].to_numpy(),
            "time_of_day": pd.to_timedelta(bucket, unit="m"),
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
        The [`calculate_net_flow`][gbfs_toolkit.calculate_net_flow] frame plus ``expected_inflow`` (mean positive net flow per
        station) and ``docking_pressure`` (= ``expected_inflow / num_docks_available``, ``NaN`` when
        no docks are free).

    See Also
    --------
    [`station_outage_rates`][gbfs_toolkit.station_outage_rates] : Saturation rate behind the pressure.
    [`service_reliability_index`][gbfs_toolkit.service_reliability_index] : Dock-availability probabilities.

    Examples
    --------
    >>> import pandas as pd
    >>> panel = pd.DataFrame({
    ...     "system_id": "s", "station_id": "a",
    ...     "fetched_at": pd.to_datetime(["2026-01-01T08:00Z", "2026-01-01T09:00Z"]),
    ...     "num_bikes_available": [5, 8], "num_docks_available": [10, 7],
    ... })
    >>> round(float(docking_pressure(panel)["docking_pressure"].iloc[0]), 1)
    0.3
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

    See Also
    --------
    [`service_reliability_index`][gbfs_toolkit.service_reliability_index] : Time-of-day service probabilities.
    [`outage_survival`][gbfs_toolkit.outage_survival] : Duration of the outages this counts.
    [`censored_time_ratio`][gbfs_toolkit.censored_time_ratio] : The same censoring as a single ratio.

    Examples
    --------
    >>> import pandas as pd
    >>> panel = pd.DataFrame({
    ...     "system_id": "s", "station_id": "a",
    ...     "num_bikes_available": [0, 0, 5, 5], "num_docks_available": [10, 10, 5, 0],
    ... })
    >>> out = station_outage_rates(panel)
    >>> float(out["stockout_rate"].iloc[0]), float(out["saturation_rate"].iloc[0])
    (0.5, 0.25)
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

    From the [`stockout_episodes`][gbfs_toolkit.stockout_episodes] event table, the empirical survival
    :math:`S(t) = \\Pr(\\text{duration} > t)` of outage durations, optionally grouped, with the
    median and P90 time-to-recovery. Strictly empirical (Kaplan-Meier reduces to the ECDF without
    censoring). Episodes still open at the observation window's edge are right-censored in the data;
    they are not imputed, so read the longest durations as lower bounds.

    Parameters
    ----------
    episodes : pandas.DataFrame
        Output of [`stockout_episodes`][gbfs_toolkit.stockout_episodes] (needs ``duration_minutes``).
    by : str, optional
        A grouping column (e.g. ``"station_id"`` or ``"kind"``); one survival curve per group.

    Returns
    -------
    pandas.DataFrame
        ``[<by>,] duration_minutes, survival, at_risk, n_episodes, median_recovery, p90_recovery``.

    References
    ----------
    Kaplan and Meier (1958), used here as a descriptive empirical survival estimator.

    See Also
    --------
    [`station_outage_rates`][gbfs_toolkit.station_outage_rates] : How often outages occur.
    [`stockout_episodes`][gbfs_toolkit.stockout_episodes] : The episode table this consumes.

    Examples
    --------
    >>> import pandas as pd
    >>> episodes = pd.DataFrame({"duration_minutes": [10, 20, 20, 60]})
    >>> float(outage_survival(episodes)["median_recovery"].iloc[0])
    20.0
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

    See Also
    --------
    [`occupancy`][gbfs_toolkit.occupancy] : Bikes / (bikes + docks) without capacity.
    [`service_reliability_index`][gbfs_toolkit.service_reliability_index] : Level of service on the normalised panel.

    Examples
    --------
    >>> import pandas as pd
    >>> panel = pd.DataFrame({
    ...     "system_id": "s", "station_id": ["a", "b"], "num_bikes_available": [10, 10]})
    >>> info = pd.DataFrame({
    ...     "system_id": "s", "station_id": ["a", "b"], "capacity": [15, 40]})
    >>> [round(float(x), 2) for x in capacity_utilization(panel, info)["utilization_rate"]]
    [0.67, 0.25]
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


def boundary_stress(panel: pd.DataFrame, *, bikes_le: int = 2, docks_le: int = 2) -> pd.DataFrame:
    """Per-station share of time *near* empty or *near* full, not just at the boundary.

    A user reads a station with two bikes left as unreliable (they may be the broken
    ones), long before it hits zero; [`station_outage_rates`][gbfs_toolkit.station_outage_rates] (strictly ``== 0``)
    undercounts that perceived stress. This reports the fraction of observations with
    at most ``bikes_le`` bikes (pick-up stress) and at most ``docks_le`` docks
    (drop-off stress), using **absolute** thresholds, since two bikes mean stress at a
    10-dock station but not at a 40-dock one. Drop-off stress is undefined for
    free-floating or zero-capacity stations (no physical docks), so it returns ``NA``
    there rather than a misleading number.

    Parameters
    ----------
    panel : pandas.DataFrame
        Panel or snapshots with ``system_id, station_id, num_bikes_available,
        num_docks_available``; uses ``capacity`` / ``is_virtual_station`` when present.
    bikes_le, docks_le : int, default 2
        A station is under pick-up / drop-off stress when its bikes / docks are at or
        below this absolute count.

    Returns
    -------
    pandas.DataFrame
        ``system_id, station_id, pickup_stress_ratio, dropoff_stress_ratio, n_obs``
        (rates in ``[0, 1]``; ``dropoff_stress_ratio`` is nullable ``NA`` for
        free-floating / zero-capacity stations).

    See Also
    --------
    [`station_outage_rates`][gbfs_toolkit.station_outage_rates] : The strict empty/full (``== 0``) rates.
    [`censored_time_ratio`][gbfs_toolkit.censored_time_ratio] : Share of demand lost at the boundary.
    [`service_reliability_index`][gbfs_toolkit.service_reliability_index] : Level-of-service probabilities.

    Examples
    --------
    >>> import pandas as pd
    >>> panel = pd.DataFrame({
    ...     "system_id": "s", "station_id": "a",
    ...     "num_bikes_available": [0, 1, 5, 10],
    ...     "num_docks_available": [10, 9, 5, 0],
    ... })
    >>> float(boundary_stress(panel)["pickup_stress_ratio"].iloc[0])
    0.5
    """
    df = panel_frame(panel)
    require_columns(
        df,
        ["system_id", "station_id", "num_bikes_available", "num_docks_available"],
        what="boundary_stress",
    )
    bikes = num(df, "num_bikes_available")
    docks = num(df, "num_docks_available")
    virtual = np.zeros(len(df), dtype=bool)
    if "is_virtual_station" in df.columns:
        virtual |= df["is_virtual_station"].fillna(False).astype(bool).to_numpy()
    if "capacity" in df.columns:
        # Only a *finite* non-positive capacity means "no physical docks"; a missing
        # (NaN) capacity is unknown, not virtual, so it must not null the dock metric.
        cap = num(df, "capacity").to_numpy()
        virtual |= np.isfinite(cap) & (cap <= 0)
    low_docks = np.where(virtual, np.nan, (docks <= docks_le).to_numpy().astype("float64"))
    work = pd.DataFrame(
        {
            "system_id": df["system_id"].to_numpy(),
            "station_id": df["station_id"].to_numpy(),
            "_low_bikes": (bikes <= bikes_le).to_numpy(),
            "_low_docks": low_docks,
        }
    )
    out = (
        work.groupby(["system_id", "station_id"], sort=False)
        .agg(
            pickup_stress_ratio=("_low_bikes", "mean"),
            dropoff_stress_ratio=("_low_docks", "mean"),
            n_obs=("_low_bikes", "size"),
        )
        .reset_index()
    )
    out["dropoff_stress_ratio"] = out["dropoff_stress_ratio"].astype("Float64")
    return out

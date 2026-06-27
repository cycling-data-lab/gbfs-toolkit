"""Descriptive research-indicator layer (added in 1.3.0 and 1.4.0).

Publication-ready descriptive metrics computed from the canonical panel and station frames:
service reliability, equity, observed dynamics, temporal structure, sampling diagnostics, and
spatial autocorrelation. Pure functions, strictly descriptive (no OD, routing, prediction or
imputation), exposed on the ``.gbfs`` accessor.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from gbfs_toolkit.core.models import require_columns
from gbfs_toolkit.core.utils import EARTH_RADIUS_M, gini, panel_frame
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
    df = panel_frame(panel)
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
    df = panel_frame(panel)
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
    df = panel_frame(panel)
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
                "temporal_gini": gini(vals),
                "peak_share": float(vals.max() / total) if total > 0 else np.nan,
                "peak_bin": int(bins[np.argmax(vals)]) if total > 0 else -1,
            }
        )
    return pd.DataFrame(rows)


def spatial_entropy(
    vehicle_panel: pd.DataFrame, *, grid_size_m: float = 200.0, time_col: str = "fetched_at"
) -> pd.DataFrame:
    """Shannon entropy of the free-floating fleet's spatial distribution over time.

    A free-floating system tends to collapse entropically (vehicles pile into city centres or
    topographic low points). Tracking the Shannon entropy of the per-snapshot distribution over a
    fixed metric grid objectifies that concentration without depending on administrative
    boundaries: high entropy is an even spread, low entropy is concentration.

    For each snapshot, vehicles are binned into ``grid_size_m`` cells (equirectangular projection)
    and :math:`H = -\\sum_i p_i \\ln p_i` is computed over the occupied cells, where :math:`p_i` is
    the share of the fleet in cell :math:`i`. ``evenness`` normalises by :math:`\\ln(\\text{cells})`
    so it is comparable across snapshots with different footprints.

    Parameters
    ----------
    vehicle_panel : pandas.DataFrame
        A history of canonical ``VehicleStatus`` rows; needs ``lat, lon`` and ``time_col``.
    grid_size_m : float, default 200.0
        Grid cell size in metres.
    time_col : str, default "fetched_at"
        Snapshot timestamp to group by.

    Returns
    -------
    pandas.DataFrame
        One row per snapshot: ``<time_col>, n_vehicles, n_cells, shannon_entropy, evenness``.
    """
    df = (
        vehicle_panel.reset_index()
        if isinstance(vehicle_panel.index, pd.MultiIndex)
        else vehicle_panel.copy()
    )
    require_columns(df, ["lat", "lon", time_col], what="spatial_entropy")
    lat = pd.to_numeric(df["lat"], errors="coerce")
    lon = pd.to_numeric(df["lon"], errors="coerce")
    finite = lat.notna() & lon.notna()
    df = df.loc[finite].copy()
    if df.empty:
        return pd.DataFrame(
            columns=[time_col, "n_vehicles", "n_cells", "shannon_entropy", "evenness"]
        )
    lat_f, lon_f = lat[finite].to_numpy(), lon[finite].to_numpy()
    mean_lat = np.deg2rad(np.mean(lat_f))
    x = EARTH_RADIUS_M * np.deg2rad(lon_f) * np.cos(mean_lat)
    y = EARTH_RADIUS_M * np.deg2rad(lat_f)
    df["_cell"] = list(
        zip(
            np.floor(x / grid_size_m).astype("int64"),
            np.floor(y / grid_size_m).astype("int64"),
            strict=True,
        )
    )

    rows = []
    for t, g in df.groupby(time_col, sort=True):
        counts = g.groupby("_cell").size().to_numpy()
        p = counts / counts.sum()
        h = float(-(p * np.log(p)).sum())
        n_cells = int(len(counts))
        rows.append(
            {
                time_col: t,
                "n_vehicles": int(len(g)),
                "n_cells": n_cells,
                "shannon_entropy": h,
                "evenness": h / np.log(n_cells) if n_cells > 1 else 0.0,
            }
        )
    return pd.DataFrame(rows)


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


def spatial_center_of_mass(
    panel: pd.DataFrame,
    *,
    freq: str = "1h",
    weight_col: str = "num_bikes_available",
    time_col: str = "fetched_at",
) -> pd.DataFrame:
    """Fleet centre of gravity over time: the weighted-mean station coordinate per period.

    Summarises the whole network's spatial dynamics as one moving point. In hilly or monocentric
    cities the centre of mass drifts downhill or toward the centre over the day, which is the
    signature of the pendular migration that forces heavy evening rebalancing.

    Parameters
    ----------
    panel : pandas.DataFrame
        A panel joined with station coordinates: needs ``lat, lon, time_col`` and ``weight_col``.
    freq : str, default "1h"
        Aggregation bin (a pandas offset alias).
    weight_col : str, default "num_bikes_available"
        Weight for the mean (e.g. available bikes).

    Returns
    -------
    pandas.DataFrame
        ``period, center_lat, center_lon, total_weight``.
    """
    df = panel.reset_index() if isinstance(panel.index, pd.MultiIndex) else panel.copy()
    require_columns(df, ["lat", "lon", time_col, weight_col], what="spatial_center_of_mass")
    w = pd.to_numeric(df[weight_col], errors="coerce").fillna(0.0).to_numpy()
    lat = pd.to_numeric(df["lat"], errors="coerce").to_numpy()
    lon = pd.to_numeric(df["lon"], errors="coerce").to_numpy()
    period = pd.to_datetime(df[time_col]).dt.floor(freq)
    work = pd.DataFrame({"period": period.to_numpy(), "_wlat": w * lat, "_wlon": w * lon, "_w": w})
    agg = work.groupby("period").sum()
    out = pd.DataFrame(
        {
            "period": agg.index,
            "center_lat": agg["_wlat"] / agg["_w"].where(agg["_w"] > 0),
            "center_lon": agg["_wlon"] / agg["_w"].where(agg["_w"] > 0),
            "total_weight": agg["_w"].to_numpy(),
        }
    ).reset_index(drop=True)
    return out


def diurnal_summary_stats(
    panel: pd.DataFrame, *, value_col: str = "num_bikes_available", time_col: str = "fetched_at"
) -> pd.DataFrame:
    """Hour-of-day summary of a quantity: mean, median and robust P5/P95 bands.

    The aggregation behind the classic diurnal usage curve with its uncertainty ribbon. Provided
    once so studies do not re-derive ``groupby(hour).agg(...)`` with ad-hoc, outlier-sensitive
    percentiles. Convert the panel to local time first for local-hour semantics.

    Returns
    -------
    pandas.DataFrame
        ``hour`` (0 to 23) with ``mean, median, p05, p95, n``.
    """
    df = panel.reset_index() if isinstance(panel.index, pd.MultiIndex) else panel.copy()
    require_columns(df, [value_col, time_col], what="diurnal_summary_stats")
    work = pd.DataFrame(
        {
            "hour": pd.to_datetime(df[time_col]).dt.hour.to_numpy(),
            "_v": pd.to_numeric(df[value_col], errors="coerce").to_numpy(),
        }
    )
    g = work.groupby("hour")["_v"]
    out = g.agg(["mean", "median", "size"]).rename(columns={"size": "n"})
    out["p05"] = g.quantile(0.05)
    out["p95"] = g.quantile(0.95)
    return out.reset_index()[["hour", "mean", "median", "p05", "p95", "n"]]


def local_morans_i(
    info: pd.DataFrame,
    value_col: str,
    *,
    k: int = 8,
    permutations: int = 999,
    seed: int = 0,
) -> pd.DataFrame:
    """Local Moran's I (LISA): per-station spatial-autocorrelation hotspots and cold spots.

    Where :func:`morans_i` returns one global number ("is there a pattern?"), LISA localises it:
    each station gets a local statistic, a permutation pseudo p-value, and a cluster label, so a
    study can map *where* the low-availability cold spots or high-turnover hot spots are.

    With deviations :math:`z_i = x_i - \\bar{x}` and row-standardised k-nearest-neighbour weights,
    the local statistic is :math:`I_i = (z_i / m_2)\\sum_j w_{ij} z_j`, where
    :math:`m_2 = \\frac{1}{n}\\sum_i z_i^2`. Significance is a conditional-permutation pseudo
    p-value; each station is labelled ``HH`` (high value, high neighbours), ``LL``, ``HL`` or
    ``LH`` (spatial outliers) when significant, else ``ns``. Requires scipy (``[geo]`` weights).

    Parameters
    ----------
    info : pandas.DataFrame
        Canonical station inventory with ``lat, lon`` and ``value_col``.
    value_col : str
        The variable to test (for example occupancy or turnover).
    k : int, default 8
        Number of nearest neighbours for the spatial weights.
    permutations : int, default 999
        Permutations for the pseudo p-value.
    seed : int, default 0
        Seed for the permutation draw (reproducible).

    Returns
    -------
    pandas.DataFrame
        Aligned to ``info``: ``local_i, z_score, p_value, cluster_type`` (and ``station_id`` when
        present). Non-finite inputs yield ``NaN`` / ``"ns"``.

    References
    ----------
    Anselin, L. (1995). Local Indicators of Spatial Association (LISA). *Geographical Analysis*,
    27(2), 93-115.
    """
    from gbfs_toolkit.spatial.geometry import GeoKDTree

    require_columns(info, ["lat", "lon", value_col], what="local_morans_i")
    base = info.reset_index(drop=True)
    lat = pd.to_numeric(base["lat"], errors="coerce").to_numpy()
    lon = pd.to_numeric(base["lon"], errors="coerce").to_numpy()
    x = pd.to_numeric(base[value_col], errors="coerce").to_numpy()
    finite = np.isfinite(lat) & np.isfinite(lon) & np.isfinite(x)

    out = pd.DataFrame(index=base.index)
    if "station_id" in base.columns:
        out["station_id"] = base["station_id"]
    out["local_i"] = np.nan
    out["z_score"] = np.nan
    out["p_value"] = np.nan
    out["cluster_type"] = "ns"

    n = int(finite.sum())
    kk = min(k, n - 1)
    if n < 3 or kk < 1:
        return out

    pos = np.where(finite)[0]
    lat_f, lon_f, xf = lat[pos], lon[pos], x[pos]
    _, idx = GeoKDTree(lat_f, lon_f).query(lat_f, lon_f, k=kk + 1)
    neighbours = np.asarray(idx)[:, 1 : kk + 1]  # drop self

    z = xf - xf.mean()
    m2 = float((z**2).mean())
    if m2 == 0:
        return out
    lag = z[neighbours].mean(axis=1)
    local_i = (z / m2) * lag

    rng = np.random.default_rng(seed)
    abs_obs = np.abs(local_i)
    ge = np.zeros(n)
    s1 = np.zeros(n)
    s2 = np.zeros(n)
    for _ in range(permutations):
        pz = rng.permutation(z)
        i_perm = (z / m2) * pz[neighbours].mean(axis=1)
        ge += np.abs(i_perm) >= abs_obs
        s1 += i_perm
        s2 += i_perm**2
    p = (ge + 1.0) / (permutations + 1.0)
    mean_perm = s1 / permutations
    std_perm = np.sqrt(np.maximum(s2 / permutations - mean_perm**2, 1e-12))
    zscore = (local_i - mean_perm) / std_perm

    sig = p <= 0.05
    hi_z, hi_lag = z > 0, lag > 0
    ctype = np.full(n, "ns", dtype=object)
    ctype[sig & hi_z & hi_lag] = "HH"
    ctype[sig & ~hi_z & ~hi_lag] = "LL"
    ctype[sig & hi_z & ~hi_lag] = "HL"
    ctype[sig & ~hi_z & hi_lag] = "LH"

    out.loc[pos, "local_i"] = local_i
    out.loc[pos, "z_score"] = zscore
    out.loc[pos, "p_value"] = p
    out.loc[pos, "cluster_type"] = ctype
    return out


def diurnal_bimodality(
    panel: pd.DataFrame, *, value_col: str = "num_bikes_available", time_col: str = "fetched_at"
) -> pd.DataFrame:
    """Sarle's bimodality coefficient of each station's diurnal profile.

    Clustering yields unsupervised typologies; this yields a single, continuous, thresholded
    scalar that separates commuter stations (a bimodal morning/evening profile) from recreational
    or residential ones (unimodal). For the mean hourly profile with sample skewness :math:`g_1`
    and excess kurtosis :math:`g_2`,

    .. math::
        \\mathrm{BC} = \\frac{g_1^2 + 1}{g_2 + \\frac{3(n-1)^2}{(n-2)(n-3)}},

    and ``BC > 5/9 ≈ 0.555`` suggests bimodality.

    Returns
    -------
    pandas.DataFrame
        Per station: ``bimodality_coefficient`` (float), ``is_bimodal`` (boolean) and
        ``peak_hour`` (hour of the busiest bin).

    References
    ----------
    Pfister et al. (2013); Sarle's bimodality coefficient. Bikeshare diurnal context: Vogel et al.
    (2011).
    """
    from scipy.stats import kurtosis, skew

    df = panel.reset_index() if isinstance(panel.index, pd.MultiIndex) else panel.copy()
    require_columns(df, ["station_id", value_col, time_col], what="diurnal_bimodality")
    work = pd.DataFrame(
        {
            "station_id": df["station_id"].to_numpy(),
            "hour": pd.to_datetime(df[time_col]).dt.hour.to_numpy(),
            "_v": pd.to_numeric(df[value_col], errors="coerce").to_numpy(),
        }
    )
    profiles = work.groupby(["station_id", "hour"])["_v"].mean().unstack("hour")
    rows = []
    for sid, profile in profiles.iterrows():
        a = profile.dropna().to_numpy()
        n = a.size
        if n < 4 or np.allclose(a, a[0]):
            bc = np.nan
        else:
            g1 = float(skew(a, bias=False))
            g2 = float(kurtosis(a, fisher=True, bias=False))
            denom = g2 + 3.0 * (n - 1) ** 2 / ((n - 2) * (n - 3))
            bc = (g1**2 + 1.0) / denom if denom != 0 else np.nan
        peak_hour = int(profile.idxmax()) if profile.notna().any() else -1
        rows.append(
            {
                "station_id": sid,
                "bimodality_coefficient": bc,
                "is_bimodal": pd.NA if np.isnan(bc) else bool(bc > 5 / 9),
                "peak_hour": peak_hour,
            }
        )
    out = pd.DataFrame(rows)
    out["is_bimodal"] = out["is_bimodal"].astype("boolean")
    return out

"""Temporal structure of usage: autocorrelation, peaking, diurnal profiles, calendar context.

Pure descriptive functions over the canonical panel and station frames. Strictly descriptive
(no OD, routing, prediction or imputation), exposed on the ``.gbfs`` accessor.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from gbfs_toolkit.core.models import require_columns
from gbfs_toolkit.core.utils import gini, num, panel_frame
from gbfs_toolkit.io.timeseries import calculate_net_flow

#: Period of each cyclic calendar field, for sin/cos encoding.
_CYCLE_PERIODS = {
    "minute": 60,
    "hour": 24,
    "dayofweek": 7,
    "day": 31,
    "month": 12,
    "dayofyear": 366,
}

#: Ordered time-of-day blocks added by :func:`temporal_context_features`.
TIME_BLOCKS = ["night", "am_peak", "midday", "pm_peak", "evening"]


def cyclical_time_features(
    timestamps: Any, *, fields: tuple[str, ...] = ("hour", "dayofweek", "month")
) -> pd.DataFrame:
    """Encode calendar fields as (sin, cos) pairs: the one everyone re-implements.

    Periodic time variables (hour-of-day, day-of-week, month) are discontinuous as raw integers
    (23:00 is adjacent to 00:00 but ``23`` is far from ``0``); sin/cos on the circle fixes that.
    Pass any datetime-like (Series / Index / array); returns two columns per field.

    Parameters
    ----------
    fields : tuple of str
        Any of ``minute, hour, dayofweek, day, month, dayofyear``.

    Returns
    -------
    pandas.DataFrame
        ``{field}_sin`` / ``{field}_cos`` per requested field, aligned to the input order.

    See Also
    --------
    [`temporal_context_features`][gbfs_toolkit.temporal_context_features] : Calendar context (weekend, time block).

    Examples
    --------
    >>> import pandas as pd
    >>> ts = pd.to_datetime(["2026-01-01T00:00Z", "2026-01-01T06:00Z"])
    >>> out = cyclical_time_features(ts, fields=("hour",))
    >>> out.columns.tolist()
    ['hour_sin', 'hour_cos']
    >>> round(float(out["hour_sin"].iloc[1]), 1)
    1.0
    """
    ts = pd.to_datetime(
        pd.Series(list(timestamps) if not hasattr(timestamps, "dt") else timestamps)
    )
    ts = ts.reset_index(drop=True)
    out: dict[str, np.ndarray] = {}
    for f in fields:
        if f not in _CYCLE_PERIODS:
            raise ValueError(f"unknown field {f!r}; choose from {sorted(_CYCLE_PERIODS)}")
        angle = 2 * np.pi * getattr(ts.dt, f).to_numpy() / _CYCLE_PERIODS[f]
        out[f"{f}_sin"] = np.sin(angle)
        out[f"{f}_cos"] = np.cos(angle)
    return pd.DataFrame(out)


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

    See Also
    --------
    [`diurnal_summary_stats`][gbfs_toolkit.diurnal_summary_stats] : The diurnal curve behind the rhythm.
    [`availability_synchrony`][gbfs_toolkit.availability_synchrony] : Cross-station correlation network.

    Examples
    --------
    >>> import pandas as pd
    >>> idx = pd.date_range("2026-01-01", periods=6, freq="1h", tz="UTC")
    >>> panel = pd.DataFrame({
    ...     "system_id": "s", "station_id": "a", "fetched_at": idx,
    ...     "num_bikes_available": [0, 5, 0, 5, 0, 5],
    ... })
    >>> round(float(temporal_autocorrelation(panel, lags=(2,))["acf_lag_2"].iloc[0]), 1)
    1.0
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

    See Also
    --------
    [`temporal_context_features`][gbfs_toolkit.temporal_context_features] : Add calendar context columns.

    Examples
    --------
    >>> import pandas as pd
    >>> panel = pd.DataFrame({
    ...     "station_id": "a",
    ...     "fetched_at": pd.to_datetime(["2026-01-01T08:00Z", "2026-01-01T09:00Z"]),
    ...     "num_bikes_available": [5, 3],
    ... })
    >>> weather = pd.DataFrame({
    ...     "fetched_at": pd.to_datetime(["2026-01-01T08:05Z", "2026-01-01T09:10Z"]),
    ...     "temp_c": [4.0, 6.0],
    ... })
    >>> join_exogenous_timeseries(panel, weather)["temp_c"].tolist()
    [4.0, 6.0]
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

    See Also
    --------
    [`dynamic_gini_index`][gbfs_toolkit.dynamic_gini_index] : The spatial analogue of this peaking.
    [`diurnal_summary_stats`][gbfs_toolkit.diurnal_summary_stats] : The diurnal curve being concentrated.

    Examples
    --------
    >>> import pandas as pd
    >>> panel = pd.DataFrame({
    ...     "system_id": "s", "station_id": "a",
    ...     "fetched_at": pd.to_datetime(
    ...         ["2026-01-01T08:00Z", "2026-01-01T08:30Z", "2026-01-01T18:00Z"]),
    ...     "num_bikes_available": [5, 10, 9],
    ... })
    >>> set(temporal_concentration(panel).columns) >= {"temporal_gini", "peak_share", "peak_bin"}
    True
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

    See Also
    --------
    [`diurnal_bimodality`][gbfs_toolkit.diurnal_bimodality] : Commuter-vs-recreational scalar.
    [`temporal_autocorrelation`][gbfs_toolkit.temporal_autocorrelation] : Rhythm regularity at fixed lags.

    Examples
    --------
    >>> import pandas as pd
    >>> panel = pd.DataFrame({
    ...     "fetched_at": pd.to_datetime(
    ...         ["2026-01-01T08:00Z", "2026-01-02T08:00Z", "2026-01-01T18:00Z"]),
    ...     "num_bikes_available": [4, 6, 10],
    ... })
    >>> float(diurnal_summary_stats(panel).set_index("hour").loc[8, "mean"])
    5.0
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

    See Also
    --------
    [`diurnal_summary_stats`][gbfs_toolkit.diurnal_summary_stats] : The diurnal curve this scores.
    [`cluster_diurnal_profiles`][gbfs_toolkit.cluster_diurnal_profiles] : Unsupervised diurnal typologies.

    Examples
    --------
    >>> import pandas as pd
    >>> hours = list(range(24))
    >>> panel = pd.DataFrame({
    ...     "station_id": "a",
    ...     "fetched_at": pd.to_datetime([f"2026-01-01T{h:02d}:00Z" for h in hours]),
    ...     "num_bikes_available": [10 if h in (8, 18) else 1 for h in hours],
    ... })
    >>> int(diurnal_bimodality(panel)["peak_hour"].iloc[0])
    8
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
    out = pd.DataFrame(
        rows, columns=["station_id", "bimodality_coefficient", "is_bimodal", "peak_hour"]
    )
    out["is_bimodal"] = out["is_bimodal"].astype("boolean")
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

    See Also
    --------
    [`temporal_autocorrelation`][gbfs_toolkit.temporal_autocorrelation] : Per-station rhythm regularity.

    Examples
    --------
    >>> import pandas as pd
    >>> idx = pd.date_range("2026-01-01", periods=3, freq="1h", tz="UTC")
    >>> panel = pd.DataFrame({
    ...     "station_id": ["a"] * 3 + ["b"] * 3,
    ...     "fetched_at": list(idx) * 2,
    ...     "num_bikes_available": [1, 2, 3, 2, 4, 6],
    ... })
    >>> round(float(availability_synchrony(panel, min_overlap=3)["corr"].iloc[0]), 1)
    1.0
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
        time column. Hour-of-day uses ``time_col`` **as stored**; pass a panel built with
        ``target_tz`` for local-time peaks.

    Returns
    -------
    pandas.DataFrame
        Indexed by ``(system_id, station_id)``: ``n_obs``, ``mean_bikes``, ``median_bikes``,
        ``occupancy_mean``, ``pct_time_empty``, ``pct_time_full``, ``volatility``,
        ``diurnal_amplitude``, ``peak_hour``.

    See Also
    --------
    [`diurnal_profiles`][gbfs_toolkit.diurnal_profiles] : The per-station diurnal curves.
    [`diurnal_summary_stats`][gbfs_toolkit.diurnal_summary_stats] : System-wide hourly summary.

    Examples
    --------
    >>> import pandas as pd
    >>> panel = pd.DataFrame({
    ...     "system_id": "s", "station_id": "a",
    ...     "fetched_at": pd.to_datetime(["2026-01-01T08:00Z", "2026-01-01T18:00Z"]),
    ...     "num_bikes_available": [0, 10], "num_docks_available": [10, 0],
    ... })
    >>> float(availability_stats(panel)["pct_time_empty"].iloc[0])
    0.5
    """
    df = panel.reset_index() if isinstance(panel.index, pd.MultiIndex) else panel.copy()
    bikes, docks = num(df, "num_bikes_available"), num(df, "num_docks_available")
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


def _time_values(df: pd.DataFrame, time_col: str) -> pd.DatetimeIndex:
    """Datetime values from a column or a matching MultiIndex level."""
    names = list(df.index.names or [])
    if isinstance(df.index, pd.MultiIndex) and time_col in names:
        return pd.DatetimeIndex(df.index.get_level_values(time_col))
    require_columns(df, [time_col], what="temporal_context_features")
    return pd.DatetimeIndex(pd.to_datetime(df[time_col]))


def temporal_context_features(
    panel: pd.DataFrame, *, time_col: str = "fetched_at", holidays: Any = None
) -> pd.DataFrame:
    """Add standard calendar context columns for descriptive temporal analysis.

    Every descriptive model or test on bike-share data needs to isolate peaks, weekends and
    holidays. This adds them once, consistently, from a tz-aware timestamp, so each study does not
    re-derive error-prone ``dt.dayofweek`` and ``pd.cut`` rules (and the UTC-versus-local traps
    that come with them). Convert to local time first for local-calendar semantics.

    Parameters
    ----------
    panel : pandas.DataFrame
        Any frame with a tz-aware datetime in ``time_col`` (a column or a MultiIndex level).
    time_col : str, default "fetched_at"
        The timestamp to derive context from.
    holidays : optional
        A collection of dates (anything :func:`pandas.to_datetime` accepts). When given, an
        ``is_holiday`` boolean column is added; omitted otherwise (no silent assumption).

    Returns
    -------
    pandas.DataFrame
        A copy of ``panel`` with ``is_weekend`` (boolean), ``time_block`` (ordered Categorical of
        :data:`TIME_BLOCKS`) and, when ``holidays`` is given, ``is_holiday`` (boolean).

    See Also
    --------
    [`cyclical_time_features`][gbfs_toolkit.cyclical_time_features] : Smooth sin/cos calendar encodings.
    [`join_exogenous_timeseries`][gbfs_toolkit.join_exogenous_timeseries] : Attach an external series (weather).

    Examples
    --------
    >>> import pandas as pd
    >>> from gbfs_toolkit import temporal_context_features
    >>> df = pd.DataFrame({"fetched_at": pd.to_datetime(
    ...     ["2026-06-27 08:30", "2026-06-29 23:00"], utc=True)})
    >>> out = temporal_context_features(df)
    >>> list(out["time_block"])
    ['am_peak', 'evening']
    >>> out["is_weekend"].tolist()
    [True, False]
    """
    out = panel.copy()
    ts = _time_values(out, time_col)
    hour = ts.hour
    block = np.select(
        [hour < 7, hour < 10, hour < 16, hour < 19],
        ["night", "am_peak", "midday", "pm_peak"],
        default="evening",
    )
    out["is_weekend"] = pd.array(ts.dayofweek >= 5, dtype="boolean")
    out["time_block"] = pd.Categorical(block, categories=TIME_BLOCKS, ordered=True)
    if holidays is not None:
        hol = set(pd.DatetimeIndex(pd.to_datetime(list(holidays))).normalize())
        out["is_holiday"] = pd.array(pd.DatetimeIndex(ts.normalize()).isin(hol), dtype="boolean")
    return out

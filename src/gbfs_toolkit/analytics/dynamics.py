"""Observed flow dynamics: drift, asymmetry, turnover and sampling vulnerability.

Descriptive reconstructions of *observed* inventory change from station-aggregate counts.
No OD/trip inference (not identifiable from aggregate counts). Exposed on the ``.gbfs`` accessor.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from gbfs_toolkit.core.models import require_columns
from gbfs_toolkit.core.utils import project_meters
from gbfs_toolkit.io.timeseries import calculate_net_flow


def rebalancing_tension(
    panel: pd.DataFrame,
    *,
    time_col: str = "fetched_at",
    value_col: str = "num_bikes_available",
    target: object = "historical_mean",
) -> pd.Series:
    """Minimum-work spatial rebalancing tension per timestamp, in bike-kilometres.

    At each timestamp, the Wasserstein-1 (earth-mover) distance between the spatial
    distribution of available bikes and a target distribution, scaled by the fleet
    size: the minimal bikes x kilometres of relocation that would bring the system
    to its target. A single scalar of *instantaneous spatial fragmentation*, purely
    descriptive: no trip, OD or movement is inferred, only the optimal-transport
    lower bound on the work an operator would need.

    Parameters
    ----------
    panel : pandas.DataFrame
        Availability panel with ``station_id, lat, lon``, ``time_col`` and
        ``value_col`` (available bikes).
    time_col, value_col : str
        Timestamp and the per-station available-bike column.
    target : "historical_mean" or pandas.Series
        Reference state. ``"historical_mean"`` (default) uses each station's mean
        stock over the panel, so tension is the departure from the system's usual
        spatial configuration. Pass a Series indexed by ``station_id`` to supply your
        own target stock (BYOD), e.g. a 50%-occupancy target.

    Returns
    -------
    pandas.Series
        Tension in bike-kilometres indexed by timestamp (``NaN`` where the fleet is
        empty at that timestamp).

    References
    ----------
    Rubner, Tomasi & Guibas (2000). The Earth Mover's Distance. *IJCV*, 40(2).

    See Also
    --------
    [`cumulative_imbalance`][gbfs_toolkit.cumulative_imbalance] : Per-station drift behind the tension.
    [`flow_asymmetry_ratio`][gbfs_toolkit.flow_asymmetry_ratio] : Structural source/sink roles.
    [`calculate_net_flow`][gbfs_toolkit.calculate_net_flow] : The observed flow this builds on.

    Examples
    --------
    >>> import pandas as pd
    >>> panel = pd.DataFrame({
    ...     "station_id": ["a", "b"], "lat": [48.85, 48.95], "lon": [2.35, 2.35],
    ...     "fetched_at": pd.Timestamp("2026-01-01T08:00Z"),
    ...     "num_bikes_available": [10, 0],
    ... })
    >>> tension = rebalancing_tension(panel, target=pd.Series({"a": 5, "b": 5}))
    >>> float(tension.iloc[0]) > 0
    True
    """
    from scipy.stats import wasserstein_distance_nd

    require_columns(
        panel, ["station_id", "lat", "lon", time_col, value_col], what="rebalancing_tension"
    )
    coords = panel.groupby("station_id")[["lat", "lon"]].first()
    finite = np.isfinite(coords["lat"].to_numpy()) & np.isfinite(coords["lon"].to_numpy())
    coords = coords[finite]
    if len(coords) < 2:
        return pd.Series(dtype="float64", name="rebalancing_tension_bike_km")
    proj = project_meters(coords["lat"].to_numpy(), coords["lon"].to_numpy())

    if isinstance(target, str):
        if target != "historical_mean":
            raise ValueError("target must be 'historical_mean' or a Series")
        tgt = panel.groupby("station_id")[value_col].mean()
    else:
        tgt = pd.Series(target)
    tgt = pd.to_numeric(tgt.reindex(coords.index), errors="coerce").fillna(0.0).to_numpy()
    if tgt.sum() <= 0:
        return pd.Series(dtype="float64", name="rebalancing_tension_bike_km")
    tgt_w = tgt / tgt.sum()

    result: dict = {}
    for ts, group in panel.groupby(time_col):
        cur = (
            pd.to_numeric(group.groupby("station_id")[value_col].sum(), errors="coerce")
            .reindex(coords.index)
            .fillna(0.0)
            .to_numpy()
        )
        total = cur.sum()
        if total <= 0:
            result[ts] = float("nan")
            continue
        w1_m = wasserstein_distance_nd(proj, proj, cur / total, tgt_w)
        result[ts] = float(w1_m) * float(total) / 1000.0  # bike-kilometres
    return pd.Series(result, name="rebalancing_tension_bike_km")


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

    See Also
    --------
    [`calculate_net_flow`][gbfs_toolkit.calculate_net_flow] : The per-interval flow this accumulates.
    [`flow_asymmetry_ratio`][gbfs_toolkit.flow_asymmetry_ratio] : In/out balance of the same flow.
    [`fleet_turnover_proxy`][gbfs_toolkit.fleet_turnover_proxy] : System-level turnover from the same flow.

    Examples
    --------
    >>> import pandas as pd
    >>> panel = pd.DataFrame({
    ...     "system_id": "s", "station_id": "a",
    ...     "fetched_at": pd.to_datetime(
    ...         ["2026-01-01T08:00Z", "2026-01-01T09:00Z", "2026-01-01T10:00Z"]),
    ...     "num_bikes_available": [10, 7, 9],
    ... })
    >>> cumulative_imbalance(panel)["cumulative_drift"].tolist()
    [0.0, -3.0, -1.0]
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

    See Also
    --------
    [`calculate_net_flow`][gbfs_toolkit.calculate_net_flow] : The flow whose sampling limit this probes.
    [`fleet_turnover_proxy`][gbfs_toolkit.fleet_turnover_proxy] : The turnover proxy this cautions about.

    Examples
    --------
    >>> import pandas as pd
    >>> panel = pd.DataFrame({
    ...     "system_id": "s", "station_id": "a",
    ...     "fetched_at": pd.to_datetime(
    ...         ["2026-01-01T08:00Z", "2026-01-01T09:00Z", "2026-01-01T10:00Z"]),
    ...     "num_bikes_available": [10, 7, 9],
    ... })
    >>> float(aliasing_vulnerability(panel)["high_frequency_loss_risk"].iloc[0])
    1.0
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


def flow_asymmetry_ratio(panel: pd.DataFrame, *, eps: float = 1e-9) -> pd.DataFrame:
    """Per-station ratio of total inflow to total outflow.

    A ratio near 1 is a self-balancing station; a ratio well below 1 (mostly departures) marks a
    morning-residential or hilltop station, and above 1 a sink. A compact descriptor of a station's
    structural role in the urban topography.

    Returns
    -------
    pandas.DataFrame
        ``system_id, station_id, inflow, outflow, asymmetry_ratio`` (= ``inflow / (outflow + eps)``).

    See Also
    --------
    [`cumulative_imbalance`][gbfs_toolkit.cumulative_imbalance] : The cumulative view of the same flow.
    [`rebalancing_tension`][gbfs_toolkit.rebalancing_tension] : The system-level spatial tension.
    [`calculate_net_flow`][gbfs_toolkit.calculate_net_flow] : The observed flow this summarises.

    Examples
    --------
    >>> import pandas as pd
    >>> panel = pd.DataFrame({
    ...     "system_id": "s", "station_id": "a",
    ...     "fetched_at": pd.to_datetime(
    ...         ["2026-01-01T08:00Z", "2026-01-01T09:00Z", "2026-01-01T10:00Z"]),
    ...     "num_bikes_available": [10, 7, 9],
    ... })
    >>> round(float(flow_asymmetry_ratio(panel)["asymmetry_ratio"].iloc[0]), 2)
    0.67
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

    See Also
    --------
    [`cumulative_imbalance`][gbfs_toolkit.cumulative_imbalance] : Per-station drift behind the activity.
    [`calculate_net_flow`][gbfs_toolkit.calculate_net_flow] : The observed flow this aggregates.

    Examples
    --------
    >>> import pandas as pd
    >>> panel = pd.DataFrame({
    ...     "system_id": "s", "station_id": "a",
    ...     "fetched_at": pd.to_datetime(
    ...         ["2026-01-01T08:00Z", "2026-01-01T09:00Z", "2026-01-01T10:00Z"]),
    ...     "num_bikes_available": [10, 7, 9],
    ... })
    >>> round(float(fleet_turnover_proxy(panel)["turnover_proxy"].iloc[0]), 3)
    0.25
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

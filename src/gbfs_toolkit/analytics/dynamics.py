"""Observed flow dynamics: drift, asymmetry, turnover and sampling vulnerability.

Descriptive reconstructions of *observed* inventory change from station-aggregate counts.
No OD/trip inference (not identifiable from aggregate counts). Exposed on the ``.gbfs`` accessor.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from gbfs_toolkit.core.models import require_columns
from gbfs_toolkit.io.timeseries import calculate_net_flow


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

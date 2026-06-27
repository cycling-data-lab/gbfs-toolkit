"""Fleet state: reconcile "where are the bikes?" and find immobile (ghost) vehicles.

GBFS routinely reports the same fleet two ways: docked bikes as aggregate counts in
``station_status``, and individual units (some parked at stations) in
``vehicle_status`` / ``free_bike_status``. Naively adding ``sum(num_bikes_available)``
to ``len(vehicles)`` double-counts every vehicle that is sitting at a station.
:func:`reconcile_fleet_state` resolves that; :func:`detect_ghost_vehicles` flags units that
never move over a long window (lost / broken / abandoned but still advertised).
"""

from __future__ import annotations

import pandas as pd

from gbfs_toolkit.geo import haversine_m
from gbfs_toolkit.models import require_columns


def _bool_col(df: pd.DataFrame, col: str) -> pd.Series:
    if col in df.columns:
        return df[col].fillna(False).astype(bool)
    return pd.Series(False, index=df.index)


def reconcile_fleet_state(
    station_status: pd.DataFrame | None = None,
    vehicles: pd.DataFrame | None = None,
) -> pd.Series:
    """Reconcile docked and free-floating feeds into one labelled fleet tally.

    Pass either or both canonical frames. Vehicles carrying a ``station_id`` are treated as
    parked at a station (already represented in ``station_status``) and are **not** added to
    the deployed total, so the two feeds don't double-count; that overlap is reported as
    ``docked_in_vehicle_feed`` / ``double_count_avoided`` for transparency.

    Returns
    -------
    pandas.Series (``Int64``) with:
        ``available_in_stations``: Σ ``num_bikes_available`` (docked, rentable).
        ``free_floating_available`` / ``_reserved`` / ``_disabled``: vehicles **not** at a
        station, split by state.
        ``docked_in_vehicle_feed``: vehicles that *are* at a station (overlap with the
        station counts).
        ``total_deployed``: physically on the street: stations + all free-floating
        (available + reserved + disabled), overlap excluded.
        ``total_rentable``: available in stations + available free-floating.
        ``double_count_avoided``: vehicles that a naive sum would have double-counted
        (non-zero only when both feeds are given).
    """
    out: dict[str, int] = {}

    in_stations = 0
    if station_status is not None and len(station_status):
        in_stations = int(
            pd.to_numeric(station_status["num_bikes_available"], errors="coerce").fillna(0).sum()
        )
    out["available_in_stations"] = in_stations

    ff_available = ff_reserved = ff_disabled = docked_in_vehicle_feed = 0
    if vehicles is not None and len(vehicles):
        at_station = (
            vehicles["station_id"].notna()
            if "station_id" in vehicles.columns
            else pd.Series(False, index=vehicles.index)
        )
        disabled = _bool_col(vehicles, "is_disabled")
        reserved = _bool_col(vehicles, "is_reserved")
        free = ~at_station
        docked_in_vehicle_feed = int(at_station.sum())
        ff_disabled = int((free & disabled).sum())
        ff_reserved = int((free & ~disabled & reserved).sum())
        ff_available = int((free & ~disabled & ~reserved).sum())

    out["free_floating_available"] = ff_available
    out["free_floating_reserved"] = ff_reserved
    out["free_floating_disabled"] = ff_disabled
    out["docked_in_vehicle_feed"] = docked_in_vehicle_feed
    out["total_deployed"] = in_stations + ff_available + ff_reserved + ff_disabled
    out["total_rentable"] = in_stations + ff_available
    both = station_status is not None and vehicles is not None
    out["double_count_avoided"] = docked_in_vehicle_feed if both else 0

    return pd.Series(out, dtype="Int64")


def detect_ghost_vehicles(
    vehicle_panel: pd.DataFrame,
    *,
    idle_days: float = 14.0,
    move_threshold_m: float = 50.0,
) -> pd.DataFrame:
    """Flag immobile ("ghost") vehicles from a longitudinal vehicle panel.

    A unit advertised at (essentially) the same coordinates for a long stretch is almost
    certainly lost, broken, or abandoned, yet it inflates availability. Given a panel of
    free-floating vehicle snapshots over time, this measures each vehicle's displacement from
    its first observed position and flags those that never moved beyond ``move_threshold_m``
    across a span of at least ``idle_days``.

    Parameters
    ----------
    vehicle_panel : pandas.DataFrame
        Long frame of vehicle snapshots with ``system_id, vehicle_id, lat, lon, fetched_at``
        (e.g. concatenated :func:`~gbfs_toolkit.to_canonical_vehicles` outputs). Note GBFS 2.1+
        rotates ``vehicle_id`` for privacy; ghost detection is only meaningful where the feed
        keeps stable ids.
    idle_days : float, default 14
        Minimum observed span (first→last sighting) for a vehicle to qualify.
    move_threshold_m : float, default 50
        Maximum great-circle displacement (metres) from the first position to count as immobile
        (absorbs GPS jitter).

    Returns
    -------
    pandas.DataFrame
        Indexed by ``(system_id, vehicle_id)``: ``first_seen``, ``last_seen``, ``n_obs``,
        ``observed_days``, ``max_displacement_m``, ``is_ghost``.
    """
    df = (
        vehicle_panel.reset_index()
        if isinstance(vehicle_panel.index, pd.MultiIndex)
        else vehicle_panel.copy()
    )
    require_columns(
        df, ["system_id", "vehicle_id", "lat", "lon", "fetched_at"], what="detect_ghost_vehicles"
    )
    df = df[["system_id", "vehicle_id", "lat", "lon", "fetched_at"]].copy()
    df["fetched_at"] = pd.to_datetime(df["fetched_at"], utc=True)
    df = df.sort_values(["system_id", "vehicle_id", "fetched_at"])

    keys = ["system_id", "vehicle_id"]
    first = (
        df.groupby(keys, sort=False)
        .first()[["lat", "lon"]]
        .rename(columns={"lat": "_lat0", "lon": "_lon0"})
    )
    m = df.merge(first, on=keys)
    m["_disp"] = haversine_m(m["lat"], m["lon"], m["_lat0"], m["_lon0"])

    g = m.groupby(keys, sort=False)
    out = g.agg(
        first_seen=("fetched_at", "min"),
        last_seen=("fetched_at", "max"),
        n_obs=("fetched_at", "size"),
        max_displacement_m=("_disp", "max"),
    )
    out["observed_days"] = (out["last_seen"] - out["first_seen"]).dt.total_seconds() / 86400
    out["max_displacement_m"] = out["max_displacement_m"].round(1)
    out["observed_days"] = out["observed_days"].round(2)
    out["is_ghost"] = (out["observed_days"] >= idle_days) & (
        out["max_displacement_m"] <= move_threshold_m
    )
    return out[
        ["first_seen", "last_seen", "n_obs", "observed_days", "max_displacement_m", "is_ghost"]
    ]


def vehicle_idle_time(
    vehicle_panel: pd.DataFrame,
    *,
    threshold_hours: float = 48.0,
    move_threshold_m: float = 50.0,
) -> pd.DataFrame:
    """Fraction of the fleet that has not moved for ``threshold_hours``, as a time series.

    Operators advertise large fleets, but researchers suspect a sizeable share is abandoned,
    broken (without an ``is_disabled`` flag) or stuck in courtyards. For each snapshot this reports
    the share of vehicles whose position has not changed (beyond ``move_threshold_m``) for at least
    ``threshold_hours``, quantifying the "zombie fleet".

    Requires stable ``vehicle_id`` over the window. GBFS 2.1+ rotates ids for privacy; idle
    detection is only meaningful where the feed keeps them stable.

    Parameters
    ----------
    vehicle_panel : pandas.DataFrame
        Long frame of vehicle snapshots with ``system_id, vehicle_id, lat, lon, fetched_at``.
    threshold_hours : float, default 48.0
        Idle duration above which a vehicle counts as idle.
    move_threshold_m : float, default 50.0
        Displacement (great-circle metres) above which a vehicle is considered to have moved.

    Returns
    -------
    pandas.DataFrame
        ``system_id, fetched_at, n_vehicles, n_idle, idle_fraction`` (one row per snapshot).
    """
    df = (
        vehicle_panel.reset_index()
        if isinstance(vehicle_panel.index, pd.MultiIndex)
        else vehicle_panel.copy()
    )
    require_columns(
        df, ["system_id", "vehicle_id", "lat", "lon", "fetched_at"], what="vehicle_idle_time"
    )
    df = df.sort_values(["system_id", "vehicle_id", "fetched_at"]).reset_index(drop=True)
    keys = [df["system_id"], df["vehicle_id"]]
    grp = df.groupby(["system_id", "vehicle_id"], sort=False)
    prev_lat = grp["lat"].shift().to_numpy()
    prev_lon = grp["lon"].shift().to_numpy()
    disp = pd.Series(
        haversine_m(df["lat"].to_numpy(), df["lon"].to_numpy(), prev_lat, prev_lon), index=df.index
    )
    moved = (disp > move_threshold_m).mask(disp.isna(), True)
    move_time = pd.to_datetime(df["fetched_at"]).where(moved.to_numpy()).groupby(keys).ffill()
    idle_hours = (pd.to_datetime(df["fetched_at"]) - move_time).dt.total_seconds() / 3600.0
    df["_idle"] = (idle_hours >= threshold_hours).to_numpy()
    out = (
        df.groupby(["system_id", "fetched_at"])
        .agg(n_vehicles=("vehicle_id", "size"), n_idle=("_idle", "sum"))
        .reset_index()
    )
    out["idle_fraction"] = out["n_idle"] / out["n_vehicles"]
    return out

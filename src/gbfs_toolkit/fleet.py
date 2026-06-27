"""Fleet reconciliation — one authoritative answer to "where are the bikes?".

GBFS routinely reports the same fleet two ways: docked bikes as aggregate counts in
``station_status``, and individual units (some parked at stations) in
``vehicle_status`` / ``free_bike_status``. Naively adding ``sum(num_bikes_available)``
to ``len(vehicles)`` double-counts every vehicle that is sitting at a station. This
module reconciles the two feeds into a single, labelled tally and surfaces the overlap
rather than hiding it.
"""

from __future__ import annotations

import pandas as pd


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
        ``available_in_stations`` — Σ ``num_bikes_available`` (docked, rentable).
        ``free_floating_available`` / ``_reserved`` / ``_disabled`` — vehicles **not** at a
        station, split by state.
        ``docked_in_vehicle_feed`` — vehicles that *are* at a station (overlap with the
        station counts).
        ``total_deployed`` — physically on the street: stations + all free-floating
        (available + reserved + disabled), overlap excluded.
        ``total_rentable`` — available in stations + available free-floating.
        ``double_count_avoided`` — vehicles that a naive sum would have double-counted
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

"""Bikeshare ↔ public transit: first/last-mile linkage.

Identify which docks act as feeders for rail/bus by spatial proximity to GTFS stops.
Pure spatial joins on the shared :class:`~gbfs_toolkit.GeoKDTree`; **Bring Your Own GTFS**:
you pass a plain ``stops`` DataFrame (the universally-available ``stops.txt``), so the
library never touches a transit API and never breaks when a GTFS schema shifts. No
schedules / ``stop_times`` (proximity only, by design).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from gbfs_toolkit.geo import GeoKDTree
from gbfs_toolkit.models import require_columns

# GTFS stops.txt column aliases (lat/lon naming varies a little in the wild).
_LAT_ALIASES = ("stop_lat", "lat", "latitude")
_LON_ALIASES = ("stop_lon", "lon", "lng", "longitude")
_ID_ALIASES = ("stop_id", "id")


def _pick(df: pd.DataFrame, aliases: tuple[str, ...], what: str) -> str:
    for a in aliases:
        if a in df.columns:
            return a
    raise KeyError(f"transit stops frame is missing a {what} column (tried {aliases})")


def link_transit_stops(
    info: pd.DataFrame,
    stops: pd.DataFrame,
    *,
    radius_m: float = 200.0,
) -> pd.DataFrame:
    """Attach transit-proximity metrics to each station.

    Parameters
    ----------
    info : pandas.DataFrame
        Canonical station inventory (needs ``lat``, ``lon``).
    stops : pandas.DataFrame
        Transit stops (GTFS ``stops.txt`` style): a ``stop_id`` and lat/lon columns
        (``stop_lat``/``stop_lon`` or common aliases).
    radius_m : float, default 200
        First/last-mile threshold: a station is a *feeder* if a stop is within this distance.

    Returns
    -------
    pandas.DataFrame
        ``info`` plus ``nearest_stop_id``, ``nearest_stop_dist_m``,
        ``n_transit_within`` (stops within ``radius_m``) and ``is_transit_feeder`` (bool).
    """
    require_columns(info, ["lat", "lon"], what="link_transit_stops(info)")
    out = info.reset_index(drop=True).copy()
    if out.empty:
        out["nearest_stop_id"] = pd.Series(dtype="object")
        out["nearest_stop_dist_m"] = pd.Series(dtype="float64")
        out["n_transit_within"] = pd.Series(dtype="int64")
        out["is_transit_feeder"] = pd.Series(dtype="bool")
        return out
    if stops.empty:
        out["nearest_stop_id"] = None
        out["nearest_stop_dist_m"] = np.inf
        out["n_transit_within"] = 0
        out["is_transit_feeder"] = False
        return out

    lat_c = _pick(stops, _LAT_ALIASES, "latitude")
    lon_c = _pick(stops, _LON_ALIASES, "longitude")
    id_c = next((a for a in _ID_ALIASES if a in stops.columns), None)
    stop_ids = stops[id_c].to_numpy() if id_c else np.arange(len(stops))

    tree = GeoKDTree(stops[lat_c], stops[lon_c])
    dist, idx = tree.query(out["lat"].to_numpy(), out["lon"].to_numpy(), k=1)
    dist, idx = np.asarray(dist).ravel(), np.asarray(idx).ravel()
    within = tree.query_radius(out["lat"].to_numpy(), out["lon"].to_numpy(), radius_m=radius_m)

    out["nearest_stop_id"] = stop_ids[idx]
    out["nearest_stop_dist_m"] = dist
    out["n_transit_within"] = [len(h) for h in within]
    out["is_transit_feeder"] = out["nearest_stop_dist_m"] <= radius_m
    return out

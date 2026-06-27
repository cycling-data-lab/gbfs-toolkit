"""Lightweight geospatial helpers — vectorised haversine, no heavy spatial deps.

``to_gdf`` bridges to GeoPandas *lazily* (optional), so the core install stays light.
Routing / isochrones are intentionally out of scope (use OSMnx / pandana).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

if TYPE_CHECKING:  # pragma: no cover
    import geopandas as gpd

_EARTH_RADIUS_M = 6_371_000.0


def haversine_m(lat1: Any, lon1: Any, lat2: Any, lon2: Any) -> np.ndarray:
    """Vectorised great-circle distance in metres between two coordinate arrays."""
    lat1, lon1, lat2, lon2 = (
        np.radians(np.asarray(a, dtype="float64")) for a in (lat1, lon1, lat2, lon2)
    )
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return _EARTH_RADIUS_M * 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))


def find_nearest_stations(
    lat: float,
    lon: float,
    info: pd.DataFrame,
    *,
    k: int = 1,
    max_radius_m: float | None = None,
) -> pd.DataFrame:
    """Return the ``k`` stations closest to ``(lat, lon)``, with a distance column.

    Parameters
    ----------
    lat, lon : float
        Query point (degrees).
    info : pandas.DataFrame
        Stations with ``lat`` and ``lon`` columns (e.g. a canonical StationInfo frame).
    k : int, default 1
        Number of nearest stations to return.
    max_radius_m : float, optional
        If given, drop stations farther than this (so fewer than ``k`` may return).

    Returns
    -------
    pandas.DataFrame
        ``info`` rows sorted by ascending distance, with a ``distance_m`` column.
    """
    d = haversine_m(lat, lon, info["lat"].to_numpy(), info["lon"].to_numpy())
    out = info.copy()
    out["distance_m"] = d
    out = out.sort_values("distance_m", kind="stable")
    if max_radius_m is not None:
        out = out[out["distance_m"] <= max_radius_m]
    return out.head(k).reset_index(drop=True)


def to_gdf(
    df: pd.DataFrame, *, lat: str = "lat", lon: str = "lon", crs: str = "EPSG:4326"
) -> gpd.GeoDataFrame:
    """Convert a frame with lat/lon columns to a GeoPandas ``GeoDataFrame`` (lazy import).

    Requires the optional ``[geo]`` extra (``geopandas``).
    """
    try:
        import geopandas as gpd
    except ImportError as e:  # pragma: no cover
        raise ImportError(
            "to_gdf requires geopandas. Install with `pip install gbfs-toolkit[geo]`."
        ) from e
    geometry = gpd.points_from_xy(df[lon], df[lat])
    return gpd.GeoDataFrame(df.copy(), geometry=geometry, crs=crs)

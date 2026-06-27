"""Lightweight geospatial helpers — the shared spatial-join primitive for the toolkit.

All coordinates are contractually **EPSG:4326** (WGS-84 lat/lon in degrees). ``GeoKDTree``
is the one radius/k-NN abstraction every module (geo, multimodal, osm) builds on, so spatial
joins are consistent across the package. ``to_gdf`` bridges to GeoPandas *lazily* (optional).
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


def _to_xyz(lat: Any, lon: Any) -> np.ndarray:
    """Project EPSG:4326 lat/lon (degrees) onto the Earth-radius sphere in 3-D metres."""
    lat_r = np.radians(np.asarray(lat, dtype="float64"))
    lon_r = np.radians(np.asarray(lon, dtype="float64"))
    cos_lat = np.cos(lat_r)
    return _EARTH_RADIUS_M * np.column_stack(
        [cos_lat * np.cos(lon_r), cos_lat * np.sin(lon_r), np.sin(lat_r)]
    )


def _chord_to_arc_m(chord: np.ndarray) -> np.ndarray:
    """Convert a 3-D chord length back to great-circle (arc) metres."""
    return 2 * _EARTH_RADIUS_M * np.arcsin(np.clip(chord / (2 * _EARTH_RADIUS_M), -1.0, 1.0))


def _arc_to_chord_m(arc_m: float) -> float:
    """Convert a great-circle radius (metres) to the 3-D chord length cKDTree expects."""
    return 2 * _EARTH_RADIUS_M * np.sin(arc_m / (2 * _EARTH_RADIUS_M))


class GeoKDTree:
    """A great-circle k-NN / radius index over lat/lon points (EPSG:4326).

    The single spatial-join primitive shared by ``find_nearest_stations``,
    ``multimodal`` and ``osm``. Built on ``scipy.spatial.cKDTree`` over a 3-D
    unit-sphere embedding, so queries are exact great-circle distances in metres
    (no flat-earth error near the poles or the antimeridian).

    Parameters
    ----------
    lat, lon : array-like
        Point coordinates in degrees (EPSG:4326).
    """

    def __init__(self, lat: Any, lon: Any) -> None:
        from scipy.spatial import cKDTree

        self._xyz = _to_xyz(lat, lon)
        self._tree = cKDTree(self._xyz)

    def __len__(self) -> int:
        return len(self._xyz)

    def query(self, lat: Any, lon: Any, k: int = 1) -> tuple[np.ndarray, np.ndarray]:
        """Nearest ``k`` indices and great-circle distances (metres) for each query point."""
        chord, idx = self._tree.query(_to_xyz(lat, lon), k=k)
        return _chord_to_arc_m(np.asarray(chord)), np.asarray(idx)

    def query_radius(self, lat: Any, lon: Any, radius_m: float) -> list[np.ndarray]:
        """Indices within ``radius_m`` great-circle metres of each query point."""
        pts = _to_xyz(np.atleast_1d(lat), np.atleast_1d(lon))
        hits = self._tree.query_ball_point(pts, _arc_to_chord_m(radius_m))
        return [np.asarray(h, dtype=int) for h in hits]


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
    out = info.copy()
    if out.empty:
        out["distance_m"] = pd.Series(dtype="float64")
        return out.reset_index(drop=True)
    tree = GeoKDTree(out["lat"], out["lon"])
    n = len(out)
    kk = n if max_radius_m is not None else min(k, n)
    dist, idx = tree.query(lat, lon, k=kk)
    dist, idx = np.asarray(dist).ravel(), np.asarray(idx).ravel()
    out = out.iloc[idx].copy()
    out["distance_m"] = dist
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

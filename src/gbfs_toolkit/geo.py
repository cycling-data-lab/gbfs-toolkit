"""Lightweight geospatial helpers: the shared spatial-join primitive for the toolkit.

All coordinates are contractually **EPSG:4326** (WGS-84 lat/lon in degrees). ``GeoKDTree``
is the one radius/k-NN abstraction every module (geo, multimodal, osm) builds on, so spatial
joins are consistent across the package. ``to_gdf`` bridges to GeoPandas *lazily* (optional).
Routing / isochrones are intentionally out of scope (use OSMnx / pandana).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from gbfs_toolkit.models import require_columns

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


def features_within(
    points: pd.DataFrame,
    features: pd.DataFrame,
    *,
    radius_m: float = 300.0,
    category_col: str | None = None,
    feature_lat: str = "lat",
    feature_lon: str = "lon",
    prefix: str = "n_",
) -> pd.DataFrame:
    """Summarise the ``features`` around each point: the generic "what's nearby" primitive.

    Works for any point dataset (transit stops, OSM POIs, shops, …). For every row of
    ``points`` it counts features within ``radius_m`` and the distance to the nearest one;
    with ``category_col`` it also breaks the count down per category (``n_<category>``).

    Parameters
    ----------
    points : pandas.DataFrame
        Query points with ``lat``/``lon`` (e.g. a canonical StationInfo frame).
    features : pandas.DataFrame
        Surrounding things, with ``feature_lat``/``feature_lon`` columns.
    radius_m : float, default 300
    category_col : str, optional
        A column in ``features`` (e.g. ``amenity``) to produce per-category counts.

    Returns
    -------
    pandas.DataFrame
        ``points`` + ``{prefix}within``, ``nearest_dist_m`` and, if ``category_col`` is
        given, one ``{prefix}<category>`` count per category.
    """
    out = points.reset_index(drop=True).copy()
    if out.empty:
        return out
    if features.empty:
        out[f"{prefix}within"] = 0
        out["nearest_dist_m"] = np.inf
        return out
    tree = GeoKDTree(features[feature_lat], features[feature_lon])
    lat, lon = out["lat"].to_numpy(), out["lon"].to_numpy()
    within = tree.query_radius(lat, lon, radius_m=radius_m)
    dist, _ = tree.query(lat, lon, k=1)
    out[f"{prefix}within"] = [len(h) for h in within]
    out["nearest_dist_m"] = np.asarray(dist).ravel()
    if category_col is not None and category_col in features:
        cats = features[category_col].to_numpy()
        for c in sorted(pd.unique(pd.Series(cats).dropna())):
            col = f"{prefix}{c}"
            out[col] = [int((cats[h] == c).sum()) for h in within]
    return out


def stations_near(
    points: pd.DataFrame,
    info: pd.DataFrame,
    *,
    radius_m: float = 300.0,
    point_lat: str = "lat",
    point_lon: str = "lon",
) -> pd.DataFrame:
    """For each external point, how many stations are nearby: the accessibility primitive.

    The inverse of :func:`features_within`: there you summarise things *around stations*; here
    you ask, for arbitrary places (clinics, schools, neighbourhood centroids), *how well each is
    served by stations*. Straight-line (great-circle) proximity only; no routing.

    Parameters
    ----------
    points : pandas.DataFrame
        Places of interest with ``point_lat``/``point_lon`` columns.
    info : pandas.DataFrame
        Canonical station inventory (``lat``/``lon``, optionally ``station_id``).
    radius_m : float, default 300

    Returns
    -------
    pandas.DataFrame
        ``points`` + ``n_stations_within``, ``nearest_station_dist_m`` and (if ``info`` has
        ``station_id``) ``nearest_station_id``.
    """
    out = points.reset_index(drop=True).copy()
    if out.empty:
        out["n_stations_within"] = pd.Series(dtype="int64")
        out["nearest_station_dist_m"] = pd.Series(dtype="float64")
        return out
    if info.empty:
        out["n_stations_within"] = 0
        out["nearest_station_dist_m"] = np.inf
        if "station_id" in info.columns:
            out["nearest_station_id"] = None
        return out
    tree = GeoKDTree(info["lat"], info["lon"])
    lat, lon = out[point_lat].to_numpy(), out[point_lon].to_numpy()
    within = tree.query_radius(lat, lon, radius_m=radius_m)
    dist, idx = tree.query(lat, lon, k=1)
    out["n_stations_within"] = [len(h) for h in within]
    out["nearest_station_dist_m"] = np.asarray(dist).ravel()
    if "station_id" in info.columns:
        out["nearest_station_id"] = info["station_id"].to_numpy()[np.asarray(idx).ravel()]
    return out


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


def to_geojson(
    df: pd.DataFrame,
    *,
    path: str | None = None,
    lat: str = "lat",
    lon: str = "lon",
) -> str | None:
    """Export stations / zones to GeoJSON for QGIS, kepler.gl, etc. (data, not a map).

    Accepts a plain lat/lon frame (promoted to points) or a ``GeoDataFrame`` (any geometry,
    e.g. geofencing polygons). Returns the GeoJSON string, or writes it to ``path`` and returns
    the path. Requires the optional ``[geo]`` extra.
    """
    gdf = df if hasattr(df, "geometry") else to_gdf(df, lat=lat, lon=lon)
    text = gdf.to_json()
    if path is None:
        return text
    from pathlib import Path

    Path(path).write_text(text, encoding="utf-8")
    return path


def _decay_weights(d: np.ndarray, d_max: float, decay: str) -> np.ndarray:
    """Distance-decay weights for a catchment of radius ``d_max``."""
    if decay == "none":
        return np.ones_like(d, dtype="float64")
    if decay == "linear":
        return np.clip(1.0 - d / d_max, 0.0, None)
    if decay == "gaussian":
        sigma = d_max / 3.0  # the catchment edge sits at ~3 sigma
        return np.exp(-0.5 * (d / sigma) ** 2)
    raise ValueError(f"decay must be 'gaussian', 'linear' or 'none', got {decay!r}")


def _point_latlon(frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Latitude / longitude arrays from lat/lon columns or a GeoDataFrame geometry."""
    if "lat" in frame.columns and "lon" in frame.columns:
        return (
            pd.to_numeric(frame["lat"], errors="coerce").to_numpy(),
            pd.to_numeric(frame["lon"], errors="coerce").to_numpy(),
        )
    if hasattr(frame, "geometry"):
        geom = frame.geometry
        return geom.y.to_numpy(dtype="float64"), geom.x.to_numpy(dtype="float64")
    raise ValueError("demand needs 'lat'/'lon' columns or a GeoDataFrame point geometry")


def two_step_fca(
    info: pd.DataFrame,
    demand: pd.DataFrame,
    *,
    max_distance_m: float = 800.0,
    decay: str = "gaussian",
    supply_col: str = "capacity",
    demand_col: str = "population",
) -> pd.Series:
    """Two-step floating catchment area (2SFCA) accessibility, a spatial-equity measure.

    Concentration measures (Gini, Theil) capture inequality *inside* the network; 2SFCA captures
    equity of access *to* the network from where people are, the metric health geographers use to
    find mobility deserts. Step 1 computes a supply-to-demand ratio at each station (capacity over
    the distance-weighted population in its catchment); step 2 sums those ratios, distance-weighted,
    over the stations reachable from each demand location.

    Straight-line (great-circle) proximity only; no routing. Bring your own demand layer (no
    network calls).

    Parameters
    ----------
    info : pandas.DataFrame
        Canonical station inventory with ``lat, lon`` and ``supply_col``.
    demand : pandas.DataFrame or geopandas.GeoDataFrame
        Demand locations with ``demand_col`` and either ``lat``/``lon`` columns or a point geometry.
    max_distance_m : float, default 800.0
        Catchment radius in metres.
    decay : {"gaussian", "linear", "none"}, default "gaussian"
        Distance-decay weighting within the catchment.
    supply_col, demand_col : str
        Columns holding station capacity and location demand (e.g. population).

    Returns
    -------
    pandas.Series
        Accessibility score per demand location, aligned to ``demand.index``
        (``name="accessibility_2sfca"``). Higher is better served.

    References
    ----------
    Luo and Wang (2003); Radke and Mu (2000). Applied to bike-share equity by e.g. Qian et al. (2020).
    """
    require_columns(info, ["lat", "lon", supply_col], what="two_step_fca")
    require_columns(demand, [demand_col], what="two_step_fca")
    slat = pd.to_numeric(info["lat"], errors="coerce").to_numpy()
    slon = pd.to_numeric(info["lon"], errors="coerce").to_numpy()
    supply = pd.to_numeric(info[supply_col], errors="coerce").fillna(0.0).to_numpy()
    dlat, dlon = _point_latlon(demand)
    dem = pd.to_numeric(demand[demand_col], errors="coerce").fillna(0.0).to_numpy()

    # Step 1: supply-to-demand ratio R_j at each station.
    r_j = np.zeros(len(supply), dtype="float64")
    demand_tree = GeoKDTree(dlat, dlon)
    for j, idx in enumerate(demand_tree.query_radius(slat, slon, radius_m=max_distance_m)):
        if idx.size == 0:
            continue
        d = haversine_m(slat[j], slon[j], dlat[idx], dlon[idx])
        weighted_demand = float((dem[idx] * _decay_weights(d, max_distance_m, decay)).sum())
        if weighted_demand > 0:
            r_j[j] = supply[j] / weighted_demand

    # Step 2: sum the reachable ratios at each demand location.
    access = np.zeros(len(dem), dtype="float64")
    supply_tree = GeoKDTree(slat, slon)
    for i, idx in enumerate(supply_tree.query_radius(dlat, dlon, radius_m=max_distance_m)):
        if idx.size == 0:
            continue
        d = haversine_m(dlat[i], dlon[i], slat[idx], slon[idx])
        access[i] = float((r_j[idx] * _decay_weights(d, max_distance_m, decay)).sum())

    return pd.Series(access, index=demand.index, name="accessibility_2sfca")

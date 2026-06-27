"""Geofencing / service-area zones — operator-defined polygons (``geofencing_zones.json``).

For free-floating and hybrid systems the *real* service area is the operator's polygons,
not a convex hull of stations. Parsing them unlocks scientifically sound spatial density and
equity analysis: bikes per km² within the **actual** service area, no-ride/no-park zones, and
coverage of a given set of neighbourhoods.

Requires the optional ``[geo]`` extra (geopandas + shapely). True to the BYOG philosophy,
nothing here touches the network — feed acquisition stays in :mod:`gbfs_toolkit.fetch`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

from gbfs_toolkit.models import GEOFENCING_COLUMNS

if TYPE_CHECKING:  # pragma: no cover
    import geopandas as gpd

# A global (jurisdiction-wide) default rule has no vehicle_type_ids restriction.
_NON_GEOM = [c for c in GEOFENCING_COLUMNS if c != "geometry"]


def _require_geo():
    try:
        import geopandas as gpd
        from shapely.geometry import shape

        return gpd, shape
    except ImportError as e:  # pragma: no cover
        raise ImportError(
            "Geofencing requires geopandas + shapely. Install with `pip install gbfs-toolkit[geo]`."
        ) from e


def _default_rule(rules: list[dict]) -> dict:
    """The zone's general rule — the first that applies to all vehicle types, else the first."""
    if not rules:
        return {}
    for r in rules:
        if not r.get("vehicle_type_ids"):
            return r
    return rules[0]


def _ride_allowed(rule: dict) -> bool | None:
    """Normalise the cross-version 'can you ride here' flag.

    GBFS 2.x exposes ``ride_allowed``; GBFS 3.x splits it into ``ride_start_allowed`` /
    ``ride_end_allowed``. We treat a zone as ride-allowed only if both start and end are.
    """
    if "ride_allowed" in rule:
        return bool(rule["ride_allowed"])
    if "ride_start_allowed" in rule or "ride_end_allowed" in rule:
        return bool(rule.get("ride_start_allowed", True)) and bool(
            rule.get("ride_end_allowed", True)
        )
    return None


def to_canonical_geofencing(
    raw: dict, *, system_id: str, gbfs_version: str = "2.x"
) -> gpd.GeoDataFrame:
    """Parse a ``geofencing_zones.json`` document into a canonical ``GeoDataFrame``.

    Returns one row per zone with a shapely geometry (EPSG:4326) and the columns of
    :data:`~gbfs_toolkit.models.GEOFENCING_COLUMNS`. The boolean/speed fields summarise each
    zone's *default* rule; the full per-vehicle-type ``rules`` list is preserved verbatim.

    Parameters
    ----------
    raw : dict
        Parsed ``geofencing_zones`` document (full doc or its ``data`` mapping).
    system_id : str
        Identifier stamped on every row.
    """
    gpd, shape = _require_geo()
    data = raw.get("data", raw)
    gz = data.get("geofencing_zones", data) if isinstance(data, dict) else {}
    features = gz.get("features", []) if isinstance(gz, dict) else []

    rows, geoms = [], []
    for i, feat in enumerate(features):
        geom = feat.get("geometry")
        if not geom:
            continue
        props = feat.get("properties") or {}
        rules = props.get("rules") or []
        rule = _default_rule(rules)
        rows.append(
            {
                "system_id": system_id,
                "zone_id": str(props.get("name") or i),
                "name": props.get("name"),
                "ride_allowed": _ride_allowed(rule),
                "ride_through_allowed": rule.get("ride_through_allowed"),
                "maximum_speed_kph": rule.get("maximum_speed_kph"),
                "station_parking": rule.get("station_parking"),
                "rules": rules,
            }
        )
        geoms.append(shape(geom))

    if not rows:
        return gpd.GeoDataFrame(
            {c: pd.Series(dtype="object") for c in _NON_GEOM}, geometry=[], crs="EPSG:4326"
        )
    gdf = gpd.GeoDataFrame(rows, geometry=geoms, crs="EPSG:4326")
    return gdf[[*_NON_GEOM, "geometry"]]


def zones_for_points(
    points: pd.DataFrame | gpd.GeoDataFrame,
    zones: gpd.GeoDataFrame,
    *,
    predicate: str = "within",
    columns: list[str] | None = None,
) -> gpd.GeoDataFrame:
    """Tag each point (station / vehicle) with the geofencing zone(s) that contain it.

    A spatial join — e.g. "which stations sit inside a no-parking zone?". Points outside
    every zone keep null zone columns (left join). Requires the ``[geo]`` extra.

    Parameters
    ----------
    points : pandas.DataFrame or geopandas.GeoDataFrame
        Points with ``lat``/``lon`` (a plain frame is promoted to a GeoDataFrame).
    zones : geopandas.GeoDataFrame
        Output of :func:`to_canonical_geofencing`.
    predicate : str, default "within"
        Spatial predicate (``within`` / ``intersects``).
    columns : list of str, optional
        Zone attribute columns to attach (default: ``zone_id, name, ride_allowed,
        ride_through_allowed, maximum_speed_kph, station_parking``).
    """
    gpd, _ = _require_geo()
    from gbfs_toolkit.geo import to_gdf

    pts = points if hasattr(points, "geometry") else to_gdf(points)
    attrs = columns or [
        "zone_id",
        "name",
        "ride_allowed",
        "ride_through_allowed",
        "maximum_speed_kph",
        "station_parking",
    ]
    attrs = [c for c in attrs if c in zones.columns]
    right = zones[[*attrs, "geometry"]].rename(columns={"name": "zone_name"})
    joined = gpd.sjoin(pts, right, how="left", predicate=predicate)
    return joined.drop(columns=[c for c in ("index_right",) if c in joined.columns])


def zone_area_km2(zones: gpd.GeoDataFrame, *, equal_area_crs: str = "EPSG:6933") -> pd.Series:
    """Area of each zone in km², computed in an equal-area projection (not in degrees).

    Reprojects to ``EPSG:6933`` (World Cylindrical Equal Area) so areas are metric and
    comparable across latitudes — the denominator for bikes-per-km² density. Requires ``[geo]``.
    """
    _require_geo()
    return zones.to_crs(equal_area_crs).geometry.area / 1e6

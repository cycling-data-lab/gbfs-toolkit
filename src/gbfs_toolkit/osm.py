"""What's around a station — OSM infrastructure / POIs within a radius, and a unified
"station surroundings" context combining transit + OSM.

Design: the **summarisation within a radius** is the durable, testable value and lives here;
the **data acquisition** is *Bring Your Own GeoDataFrame* (you fetch OSM with ``osmnx`` and
pass it in), so the library never depends on a live Overpass endpoint. A thin optional
``fetch_osm_around`` convenience is provided for interactive use but is network-bound.
Routing / isochrones stay out of scope (use OSMnx / pandana).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pandas as pd

from gbfs_toolkit.geo import features_within
from gbfs_toolkit.multimodal import link_transit_stops

if TYPE_CHECKING:  # pragma: no cover
    import geopandas as gpd

# Common OSM tag columns to try as the category when none is given.
_OSM_CATEGORY_GUESSES = ("amenity", "shop", "leisure", "highway", "railway", "public_transport")


def _gdf_points(gdf: gpd.GeoDataFrame) -> pd.DataFrame:
    """Reduce any GeoDataFrame to representative lat/lon points + its attribute columns."""
    pts = gdf.geometry.representative_point()
    df = pd.DataFrame(gdf.drop(columns=gdf.geometry.name))
    df["lat"] = pts.y.to_numpy()
    df["lon"] = pts.x.to_numpy()
    return df


def enrich_with_osm(
    info: pd.DataFrame,
    osm_gdf: gpd.GeoDataFrame,
    *,
    radius_m: float = 300.0,
    category_col: str | None = None,
    prefix: str = "osm_",
) -> pd.DataFrame:
    """Count nearby OSM features around each station (Bring Your Own GeoDataFrame).

    Reduces any geometry to a representative point, then summarises within ``radius_m``
    (total + per-category). Requires the optional ``[osm]`` extra (``geopandas``).

    Parameters
    ----------
    osm_gdf : geopandas.GeoDataFrame
        OSM features you fetched (e.g. ``osmnx.features_from_point``).
    category_col : str, optional
        Attribute to break counts down by; if omitted, the first present of
        ``amenity / shop / leisure / highway / railway / public_transport`` is used.
    """
    try:
        import geopandas  # noqa: F401
    except ImportError as e:  # pragma: no cover
        raise ImportError(
            "enrich_with_osm requires geopandas. Install with `pip install gbfs-toolkit[osm]`."
        ) from e
    feats = _gdf_points(osm_gdf)
    if category_col is None:
        category_col = next((c for c in _OSM_CATEGORY_GUESSES if c in feats.columns), None)
    return features_within(info, feats, radius_m=radius_m, category_col=category_col, prefix=prefix)


def station_surroundings(
    info: pd.DataFrame,
    *,
    transit: pd.DataFrame | None = None,
    osm: Any = None,
    radius_m: float = 300.0,
    transit_radius_m: float | None = None,
    osm_category_col: str | None = None,
) -> pd.DataFrame:
    """**One-shot "what's around each station"** — transit feeders + OSM features in a radius.

    Combines :func:`~gbfs_toolkit.link_transit_stops` and :func:`enrich_with_osm` /
    :func:`~gbfs_toolkit.features_within` into a single context frame.

    Parameters
    ----------
    info : pandas.DataFrame
        Canonical station inventory.
    transit : pandas.DataFrame, optional
        GTFS ``stops``-style frame; adds ``nearest_stop_dist_m``, ``n_transit_within``,
        ``is_transit_feeder``.
    osm : geopandas.GeoDataFrame or pandas.DataFrame, optional
        OSM features (GeoDataFrame → geometry reduced automatically) or a plain lat/lon
        frame; adds ``osm_within`` + per-category counts.
    radius_m : float, default 300
        Radius for OSM features (and transit if ``transit_radius_m`` is not set).
    transit_radius_m : float, optional
        Separate radius for the transit feeder test (defaults to ``radius_m``).
    """
    out = info.reset_index(drop=True).copy()
    if transit is not None:
        linked = link_transit_stops(out, transit, radius_m=transit_radius_m or radius_m)
        new = [c for c in linked.columns if c not in out.columns]
        out = pd.concat([out, linked[new]], axis=1)
    if osm is not None:
        if hasattr(osm, "geometry"):  # a GeoDataFrame
            enr = enrich_with_osm(out, osm, radius_m=radius_m, category_col=osm_category_col)
        else:  # already a lat/lon points frame
            enr = features_within(
                out, osm, radius_m=radius_m, category_col=osm_category_col, prefix="osm_"
            )
        new = [c for c in enr.columns if c not in out.columns]
        out = pd.concat([out, enr[new]], axis=1)
    return out


def fetch_osm_around(
    lat: float,
    lon: float,
    *,
    radius_m: float = 500.0,
    tags: dict | None = None,
) -> gpd.GeoDataFrame:
    """Optional convenience: fetch OSM features around a point via ``osmnx`` (network).

    Best-effort interactive helper — for reproducible pipelines, fetch once and pass the
    result to :func:`enrich_with_osm` (BYOG). Requires ``osmnx`` (``pip install osmnx``).
    """
    try:
        import osmnx as ox
    except ImportError as e:  # pragma: no cover
        raise ImportError(
            "fetch_osm_around requires osmnx (`pip install osmnx`). For reproducible runs, "
            "fetch your features once and pass them to enrich_with_osm (Bring Your Own GeoDataFrame)."
        ) from e
    tags = tags or {"amenity": True, "public_transport": True, "shop": True}
    return ox.features_from_point((lat, lon), tags=tags, dist=radius_m)

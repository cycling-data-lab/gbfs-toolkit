"""gbfs-toolkit — research-grade ingestion + semantic quality audit for GBFS feeds.

The community's :mod:`gbfs-validator` checks that a feed is *syntactically* valid;
this package checks whether it is *semantically* trustworthy and analysis-ready —
the A1–A7 taxonomy of Fossé & Pallares — and normalises feeds into a stable,
version-independent data model you can reuse across studies.

Quick start
-----------

    >>> import json, gbfs_toolkit as gb
    >>> raw = json.load(open("station_information.json"))
    >>> stations = gb.to_canonical_station_info(raw, system_id="velib")
    >>> verdict = gb.audit_static(stations)
    >>> clean = stations[~verdict["flagged"].to_numpy()]
"""

from gbfs_toolkit import models
from gbfs_toolkit.analysis import join_availability, station_state
from gbfs_toolkit.audit import audit_dynamic, audit_frames, audit_static
from gbfs_toolkit.catalog import filter_catalog, resolve, systems_catalog
from gbfs_toolkit.cluster import (
    cluster_diurnal_profiles,
    cluster_spatial,
    cluster_spectral,
    diurnal_profiles,
    label_diurnal_typology,
)
from gbfs_toolkit.fetch import (
    GBFSFeed,
    audit_feed,
    availability,
    fetch_multiple,
    parse_discovery,
)
from gbfs_toolkit.fleet import reconcile_fleet_state
from gbfs_toolkit.geo import (
    GeoKDTree,
    features_within,
    find_nearest_stations,
    haversine_m,
    to_gdf,
)
from gbfs_toolkit.geofencing import (
    to_canonical_geofencing,
    zone_area_km2,
    zones_for_points,
)
from gbfs_toolkit.models import AUDIT_FLAGS, RULES, SchemaError
from gbfs_toolkit.multimodal import link_transit_stops
from gbfs_toolkit.normalize import (
    to_canonical_pricing_plans,
    to_canonical_station_info,
    to_canonical_station_status,
    to_canonical_station_vehicle_counts,
    to_canonical_system_information,
    to_canonical_vehicle_types,
    to_canonical_vehicles,
)
from gbfs_toolkit.osm import enrich_with_osm, station_surroundings
from gbfs_toolkit.stats import (
    availability_stats,
    compare_systems,
    concentration_metrics,
    coverage_stats,
    system_profile,
)
from gbfs_toolkit.timeseries import (
    append_to_parquet,
    build_availability_panel,
    calculate_net_flow,
)

__version__ = "0.1.0"

__all__ = [
    # audit (the flagship)
    "audit_static",
    "audit_dynamic",
    "audit_frames",
    "audit_feed",
    # fetch / scrape (daily drivers)
    "GBFSFeed",
    "availability",
    "join_availability",
    "fetch_multiple",
    "parse_discovery",
    # normalise
    "to_canonical_station_info",
    "to_canonical_station_status",
    "to_canonical_station_vehicle_counts",
    "to_canonical_vehicles",
    "to_canonical_vehicle_types",
    "to_canonical_pricing_plans",
    "to_canonical_system_information",
    # catalogue
    "systems_catalog",
    "filter_catalog",
    "resolve",
    # longitudinal (data lake)
    "append_to_parquet",
    "build_availability_panel",
    "calculate_net_flow",
    # clustering ([cluster])
    "cluster_spatial",
    "cluster_spectral",
    "cluster_diurnal_profiles",
    "diurnal_profiles",
    "label_diurnal_typology",
    # multimodal & surroundings
    "link_transit_stops",
    "station_surroundings",
    "enrich_with_osm",
    # geofencing / service areas ([geo])
    "to_canonical_geofencing",
    "zones_for_points",
    "zone_area_km2",
    # fleet reconciliation
    "reconcile_fleet_state",
    # descriptive stats
    "system_profile",
    "compare_systems",
    "concentration_metrics",
    "coverage_stats",
    "availability_stats",
    # analysis & geo
    "station_state",
    "find_nearest_stations",
    "features_within",
    "haversine_m",
    "GeoKDTree",
    "to_gdf",
    # meta
    "models",
    "RULES",
    "AUDIT_FLAGS",
    "SchemaError",
    "__version__",
]

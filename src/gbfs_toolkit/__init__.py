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

from gbfs_toolkit import (
    accessor,  # noqa: F401 — registers the `.gbfs` DataFrame accessor
    models,
)
from gbfs_toolkit.analysis import (
    cyclical_time_features,
    ebikes,
    filter_vehicles,
    join_availability,
    join_pricing,
    join_vehicle_types,
    network_changes,
    occupancy,
    station_state,
)
from gbfs_toolkit.audit import audit_dynamic, audit_frames, audit_static, drop_flagged
from gbfs_toolkit.catalog import filter_catalog, normalize_operator, resolve, systems_catalog
from gbfs_toolkit.cluster import (
    cluster_diurnal_profiles,
    cluster_spatial,
    cluster_spectral,
    diurnal_profiles,
    label_diurnal_typology,
)
from gbfs_toolkit.datasets import load_example
from gbfs_toolkit.diagnostics import show_versions
from gbfs_toolkit.errors import (
    GBFSDiscoveryError,
    GBFSError,
    GBFSFetchError,
    GBFSNotModified,
    GBFSValidationError,
)
from gbfs_toolkit.fetch import (
    FeedResponse,
    GBFSFeed,
    audit_feed,
    availability,
    build_session,
    fetch_feed_json,
    fetch_multiple,
    parse_discovery,
)
from gbfs_toolkit.fleet import detect_ghost_vehicles, reconcile_fleet_state
from gbfs_toolkit.geo import (
    GeoKDTree,
    features_within,
    find_nearest_stations,
    haversine_m,
    stations_near,
    to_gdf,
    to_geojson,
)
from gbfs_toolkit.geofencing import (
    to_canonical_geofencing,
    zone_area_km2,
    zones_for_points,
)
from gbfs_toolkit.models import (
    AUDIT_FLAGS,
    RULES,
    SCHEMAS,
    SchemaError,
    coerce_schema,
    validate_schema,
)
from gbfs_toolkit.multimodal import link_transit_stops
from gbfs_toolkit.normalize import (
    to_canonical_alerts,
    to_canonical_pricing_plans,
    to_canonical_station_info,
    to_canonical_station_status,
    to_canonical_station_vehicle_counts,
    to_canonical_system_information,
    to_canonical_system_regions,
    to_canonical_vehicle_types,
    to_canonical_vehicles,
)
from gbfs_toolkit.osm import enrich_with_osm, station_surroundings
from gbfs_toolkit.stats import (
    availability_stats,
    compare_systems,
    concentration_metrics,
    coverage_stats,
    lorenz_curve,
    morans_i,
    ripley_k,
    system_profile,
)
from gbfs_toolkit.timeseries import (
    append_to_parquet,
    build_availability_panel,
    calculate_net_flow,
    coverage_report,
    detect_frozen_stations,
    flow_balance,
    generate_manifest,
    stockout_episodes,
    turnover,
)

__version__ = "1.0.0"

__all__ = [
    # audit (the flagship)
    "audit_static",
    "audit_dynamic",
    "audit_frames",
    "audit_feed",
    "drop_flagged",
    # fetch / scrape (daily drivers)
    "GBFSFeed",
    "availability",
    "join_availability",
    "fetch_multiple",
    "fetch_feed_json",
    "build_session",
    "FeedResponse",
    "parse_discovery",
    # normalise
    "to_canonical_station_info",
    "to_canonical_station_status",
    "to_canonical_station_vehicle_counts",
    "to_canonical_vehicles",
    "to_canonical_vehicle_types",
    "to_canonical_pricing_plans",
    "to_canonical_system_information",
    "to_canonical_system_regions",
    "to_canonical_alerts",
    # catalogue
    "systems_catalog",
    "filter_catalog",
    "resolve",
    "normalize_operator",
    # longitudinal (data lake)
    "append_to_parquet",
    "build_availability_panel",
    "calculate_net_flow",
    "coverage_report",
    "generate_manifest",
    "stockout_episodes",
    "turnover",
    "flow_balance",
    "detect_frozen_stations",
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
    "detect_ghost_vehicles",
    # network evolution & joins
    "network_changes",
    "join_vehicle_types",
    "join_pricing",
    "filter_vehicles",
    "ebikes",
    # descriptive stats
    "system_profile",
    "compare_systems",
    "concentration_metrics",
    "lorenz_curve",
    "coverage_stats",
    "availability_stats",
    "morans_i",
    "ripley_k",
    # analysis & geo
    "station_state",
    "occupancy",
    "cyclical_time_features",
    "find_nearest_stations",
    "features_within",
    "stations_near",
    "haversine_m",
    "GeoKDTree",
    "to_gdf",
    "to_geojson",
    # errors
    "GBFSError",
    "GBFSFetchError",
    "GBFSDiscoveryError",
    "GBFSValidationError",
    "GBFSNotModified",
    # schema / library ergonomics
    "validate_schema",
    "coerce_schema",
    "SCHEMAS",
    "load_example",
    "show_versions",
    # meta
    "models",
    "RULES",
    "AUDIT_FLAGS",
    "SchemaError",
    "__version__",
]

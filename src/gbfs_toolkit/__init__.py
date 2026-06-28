"""gbfs-toolkit: research-grade ingestion + semantic quality audit for GBFS feeds.

The community's `gbfs-validator` checks that a feed is *syntactically* valid;
this package checks whether it is *semantically* trustworthy and analysis-ready
(the A1–A7 taxonomy of Fossé & Pallares) and normalises feeds into a stable,
version-independent data model you can reuse across studies.

Quick start
-----------

    >>> import json, gbfs_toolkit as gb
    >>> raw = json.load(open("station_information.json"))
    >>> stations = gb.to_canonical_station_info(raw, system_id="velib")
    >>> verdict = gb.audit_static(stations)
    >>> clean = stations[~verdict["flagged"].to_numpy()]
"""

from gbfs_toolkit.analytics.agreement import (
    cohen_kappa,
    krippendorff_alpha,
    wilson_interval,
)
from gbfs_toolkit.analytics.clustering import (
    cluster_diurnal_profiles,
    cluster_spatial,
    cluster_spectral,
    diurnal_profiles,
    label_diurnal_typology,
)
from gbfs_toolkit.analytics.distribution import (
    compare_systems,
    concentration_metrics,
    dynamic_gini_index,
    format_paper_summary,
    lorenz_curve,
    palma_ratio,
    system_profile,
    theil_index,
)
from gbfs_toolkit.analytics.dynamics import (
    aliasing_vulnerability,
    cumulative_imbalance,
    fleet_turnover_proxy,
    flow_asymmetry_ratio,
    rebalancing_tension,
)
from gbfs_toolkit.analytics.fleet import (
    detect_ghost_vehicles,
    reconcile_fleet_state,
    vehicle_idle_time,
)
from gbfs_toolkit.analytics.frames import (
    ebikes,
    filter_vehicles,
    join_availability,
    join_pricing,
    join_vehicle_types,
    network_changes,
    occupancy,
    station_state,
)
from gbfs_toolkit.analytics.resampling import block_bootstrap_ci, effective_sample_size
from gbfs_toolkit.analytics.service import (
    boundary_stress,
    capacity_utilization,
    censored_time_ratio,
    docking_pressure,
    outage_survival,
    service_reliability_index,
    station_outage_rates,
)
from gbfs_toolkit.analytics.temporal import (
    availability_stats,
    availability_synchrony,
    cyclical_time_features,
    diurnal_bimodality,
    diurnal_summary_stats,
    join_exogenous_timeseries,
    temporal_autocorrelation,
    temporal_concentration,
    temporal_context_features,
)
from gbfs_toolkit.audit import (
    audit_catalogue,
    audit_dynamic,
    audit_frames,
    audit_sensitivity,
    audit_static,
    capacity_convention,
    classify_from_vehicle_types,
    classify_from_virtual_station,
    drop_flagged,
    flag_rate_ci,
    flag_sentinel_coordinates,
    overcapacity_ratio,
    reclassify_overcapacity,
    vehicle_id_persistence,
)
from gbfs_toolkit.core import models
from gbfs_toolkit.core.errors import (
    GBFSDiscoveryError,
    GBFSError,
    GBFSFetchError,
    GBFSNotModified,
    GBFSValidationError,
)
from gbfs_toolkit.core.models import (
    AUDIT_FLAGS,
    RULES,
    SCHEMAS,
    SchemaError,
    coerce_schema,
    require_columns,
    validate_schema,
)
from gbfs_toolkit.interfaces import (
    accessor,  # noqa: F401 (registers the `.gbfs` DataFrame accessor)
)
from gbfs_toolkit.interfaces.datasets import load_example
from gbfs_toolkit.interfaces.diagnostics import show_versions
from gbfs_toolkit.interfaces.synthetic import simulate_city
from gbfs_toolkit.io.catalog import filter_catalog, normalize_operator, resolve, systems_catalog
from gbfs_toolkit.io.fetch import (
    FeedResponse,
    GBFSFeed,
    audit_feed,
    availability,
    build_session,
    fetch_feed_json,
    fetch_multiple,
    parse_discovery,
)
from gbfs_toolkit.io.normalize import (
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
from gbfs_toolkit.io.timeseries import (
    add_local_time,
    append_to_parquet,
    build_availability_panel,
    calculate_net_flow,
    coverage_report,
    detect_frozen_stations,
    extract_snapshot_asof,
    flow_balance,
    generate_manifest,
    insert_explicit_gaps,
    resample_panel,
    stockout_episodes,
    to_wide_matrix,
    turnover,
)
from gbfs_toolkit.sim import (
    SimConfig,
    calibrate_city,
    compute_footprint,
    export_ml_dataset,
    generate_gbfs_parquet,
    simulate_city_flows,
)
from gbfs_toolkit.spatial.analytics import (
    coverage_stats,
    fdr_adjust,
    local_morans_i,
    morans_i,
    ripley_k,
    spatial_center_of_mass,
    spatial_entropy,
    spatial_outage_redundancy,
    two_step_fca,
)
from gbfs_toolkit.spatial.geofencing import (
    to_canonical_geofencing,
    zone_area_km2,
    zones_for_points,
)
from gbfs_toolkit.spatial.geometry import (
    GeoKDTree,
    features_within,
    filter_by_bbox,
    find_nearest_stations,
    haversine_m,
    stations_near,
    to_gdf,
    to_geojson,
)
from gbfs_toolkit.spatial.graph import (
    band_limited_signal,
    degree_preserving_rewire,
    knn_adjacency,
    low_freq_basis,
    normalized_laplacian,
    permute_signal,
    spectral_projection_r2,
)
from gbfs_toolkit.spatial.multimodal import link_transit_stops
from gbfs_toolkit.spatial.osm import enrich_with_osm, station_surroundings

__version__ = "3.0.0"  # x-release-please-version

__all__ = [
    # audit (the flagship)
    "audit_static",
    "audit_catalogue",
    "audit_sensitivity",
    "flag_rate_ci",
    "overcapacity_ratio",
    "reclassify_overcapacity",
    "classify_from_vehicle_types",
    "classify_from_virtual_station",
    "capacity_convention",
    "flag_sentinel_coordinates",
    "cohen_kappa",
    "krippendorff_alpha",
    "wilson_interval",
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
    "require_columns",
    "SCHEMAS",
    "load_example",
    "simulate_city",
    "show_versions",
    # flow simulator + empirical compiler (gbfs_toolkit.sim)
    "SimConfig",
    "simulate_city_flows",
    "generate_gbfs_parquet",
    "export_ml_dataset",
    "calibrate_city",
    "compute_footprint",
    # graph-signal primitives: Laplacian, null models, band-limited signals
    "knn_adjacency",
    "normalized_laplacian",
    "low_freq_basis",
    "spectral_projection_r2",
    "degree_preserving_rewire",
    "permute_signal",
    "band_limited_signal",
    # research indicators (1.3.0): service, equity, dynamics, sampling, calendar
    "service_reliability_index",
    "station_outage_rates",
    "capacity_utilization",
    "dynamic_gini_index",
    "two_step_fca",
    "flow_asymmetry_ratio",
    "fleet_turnover_proxy",
    "cumulative_imbalance",
    "docking_pressure",
    "spatial_center_of_mass",
    "spatial_entropy",
    "temporal_autocorrelation",
    "aliasing_vulnerability",
    "diurnal_summary_stats",
    "temporal_context_features",
    "vehicle_idle_time",
    "join_exogenous_timeseries",
    # advanced analytics (1.4.0): spatial LISA, synchrony, bimodality, survival, peaking
    "local_morans_i",
    "availability_synchrony",
    "diurnal_bimodality",
    "outage_survival",
    "temporal_concentration",
    # research algorithms (1.5.0): FDR, equity, accessibility, rebalancing, resampling
    "fdr_adjust",
    "theil_index",
    "palma_ratio",
    "rebalancing_tension",
    "block_bootstrap_ci",
    "effective_sample_size",
    "censored_time_ratio",
    # feed governance, service stress & panel ergonomics (1.6.0)
    "vehicle_id_persistence",
    "boundary_stress",
    "spatial_outage_redundancy",
    "format_paper_summary",
    "add_local_time",
    "resample_panel",
    "insert_explicit_gaps",
    "extract_snapshot_asof",
    "to_wide_matrix",
    "filter_by_bbox",
    # meta
    "models",
    "RULES",
    "AUDIT_FLAGS",
    "SchemaError",
    "__version__",
]

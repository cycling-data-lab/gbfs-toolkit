"""Bottom-up, mass-conserving flow simulation of GBFS systems, and an empirical compiler.

``simulate_city_flows`` generates occupancy from a dynamic gravity origin-destination flow (the
true OD is known); ``SimConfig`` exposes ablation axes for realistic chaos. ``generate_gbfs_parquet``
and ``export_ml_dataset`` package a run as data. ``calibrate_city`` fits the simulator to a real feed.
"""

from gbfs_toolkit.sim.compiler import (
    assign_roles,
    calibrate_city,
    compute_footprint,
    extract_geometry,
)
from gbfs_toolkit.sim.export import export_ml_dataset, generate_gbfs_parquet
from gbfs_toolkit.sim.flows import SimConfig, simulate_city_flows

__all__ = [
    "SimConfig",
    "simulate_city_flows",
    "generate_gbfs_parquet",
    "export_ml_dataset",
    "calibrate_city",
    "compute_footprint",
    "extract_geometry",
    "assign_roles",
]

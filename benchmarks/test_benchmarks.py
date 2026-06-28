"""Performance benchmarks for the heaviest descriptive functions.

Run with ``pytest benchmarks/ --benchmark-only`` (needs ``pytest-benchmark``). These are
not part of the unit-test suite (``benchmarks/`` is outside ``testpaths``); they exist to
profile the functions whose cost grows with the data and to catch a pathological
regression (an O(n^2) blow-up, a lost vectorisation) before it ships.

Data sizes are deliberately realistic: a week of 5-minute polling for a mid-size system is
~2000 snapshots, and a large network is a few thousand stations.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import gbfs_toolkit as gb

_RNG = np.random.default_rng(0)


def _stations(n: int) -> pd.DataFrame:
    """``n`` stations scattered over a city-sized box, with capacities."""
    return pd.DataFrame(
        {
            "system_id": "s",
            "station_id": [f"st{i}" for i in range(n)],
            "station_type": "docked_bike",
            "lat": 48.85 + _RNG.normal(0, 0.03, n),
            "lon": 2.35 + _RNG.normal(0, 0.04, n),
            "capacity": _RNG.integers(10, 40, n),
        }
    )


def _panel(n_stations: int, n_times: int) -> pd.DataFrame:
    """A status panel: ``n_stations`` x ``n_times`` snapshots (5-minute cadence)."""
    info = _stations(n_stations)
    times = pd.date_range("2026-01-01", periods=n_times, freq="5min", tz="UTC")
    frames = []
    for t in times:
        cap = info["capacity"].to_numpy()
        bikes = _RNG.integers(0, cap + 1)
        frames.append(
            pd.DataFrame(
                {
                    "system_id": "s",
                    "station_id": info["station_id"].to_numpy(),
                    "lat": info["lat"].to_numpy(),
                    "lon": info["lon"].to_numpy(),
                    "fetched_at": t,
                    "num_bikes_available": bikes,
                    "num_docks_available": cap - bikes,
                    "capacity": cap,
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def _vehicle_panel(n_vehicles: int, n_times: int) -> pd.DataFrame:
    info_lat = 48.85 + _RNG.normal(0, 0.03, n_vehicles)
    info_lon = 2.35 + _RNG.normal(0, 0.04, n_vehicles)
    times = pd.date_range("2026-01-01", periods=n_times, freq="1h", tz="UTC")
    frames = []
    for t in times:
        frames.append(
            pd.DataFrame(
                {
                    "system_id": "s",
                    "vehicle_id": [f"v{i}" for i in range(n_vehicles)],
                    "lat": info_lat + _RNG.normal(0, 1e-4, n_vehicles),
                    "lon": info_lon + _RNG.normal(0, 1e-4, n_vehicles),
                    "fetched_at": t,
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


# Built once, not measured.
_STATIONS_LARGE = _stations(4000)
_STATIONS_MED = _stations(800)
_PANEL = _panel(150, 288)  # ~43k rows: a day of 5-min polling over 150 stations
_VEHICLES = _vehicle_panel(400, 168)  # a week of hourly vehicle snapshots


# --- audit ------------------------------------------------------------------


def test_audit_static_4000_stations(benchmark):
    benchmark(gb.audit_static, _STATIONS_LARGE)


# --- spatial ----------------------------------------------------------------


def test_morans_i_800_stations(benchmark):
    benchmark(gb.morans_i, _STATIONS_MED, "capacity", k=8)


def test_local_morans_i_800_stations(benchmark):
    benchmark(gb.local_morans_i, _STATIONS_MED, "capacity", k=8)


def test_ripley_k_800_stations(benchmark):
    benchmark(gb.ripley_k, _STATIONS_MED, radii=[100, 250, 500, 1000])


def test_coverage_stats_800_stations(benchmark):
    benchmark(gb.coverage_stats, _STATIONS_MED)


def test_spatial_outage_redundancy_panel(benchmark):
    benchmark(gb.spatial_outage_redundancy, _PANEL, radius_m=300)


# --- panel analytics --------------------------------------------------------


def test_calculate_net_flow_panel(benchmark):
    benchmark(gb.calculate_net_flow, _PANEL)


def test_service_reliability_index_panel(benchmark):
    benchmark(gb.service_reliability_index, _PANEL)


def test_station_outage_rates_panel(benchmark):
    benchmark(gb.station_outage_rates, _PANEL)


def test_availability_synchrony_panel(benchmark):
    # O(n_stations^2) station pairs: the most likely scaling concern.
    benchmark(gb.availability_synchrony, _PANEL, min_overlap=10)


def test_dynamic_gini_index_panel(benchmark):
    benchmark(gb.dynamic_gini_index, _PANEL)


# --- fleet / governance -----------------------------------------------------


def test_vehicle_id_persistence_week(benchmark):
    benchmark(gb.vehicle_id_persistence, _VEHICLES, lags=("1h", "24h"))


def test_detect_ghost_vehicles_week(benchmark):
    benchmark(gb.detect_ghost_vehicles, _VEHICLES)


# --- clustering (optional sklearn) ------------------------------------------


def test_cluster_spatial_800_stations(benchmark):
    pytest.importorskip("sklearn")
    benchmark(gb.cluster_spatial, _STATIONS_MED, method="dbscan", eps_m=300, min_cluster_size=3)

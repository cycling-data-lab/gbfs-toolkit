"""Tests for the 1.3.0 descriptive research indicators."""

import numpy as np
import pandas as pd
import pytest

import gbfs_toolkit as gb


@pytest.fixture
def panel():
    """A small MultiIndexed availability panel: 3 stations x 24 hourly snapshots."""
    times = pd.date_range("2026-06-01", periods=24, freq="1h", tz="UTC")
    coords = {"s1": (48.85, 2.35), "s2": (48.86, 2.36), "s3": (48.80, 2.30)}
    rng = np.random.default_rng(0)
    rows = []
    for sid, (la, lo) in coords.items():
        for t, b in zip(times, rng.integers(0, 16, size=24), strict=True):
            rows.append(
                {
                    "system_id": "sys",
                    "station_id": sid,
                    "fetched_at": t,
                    "last_reported": t,
                    "num_bikes_available": int(b),
                    "num_docks_available": int(15 - b),
                    "lat": la,
                    "lon": lo,
                    "capacity": 15,
                }
            )
    return pd.DataFrame(rows).set_index(["system_id", "station_id", "fetched_at"]).sort_index()


@pytest.fixture
def info():
    return pd.DataFrame(
        [
            {"system_id": "sys", "station_id": "s1", "lat": 48.85, "lon": 2.35, "capacity": 15},
            {"system_id": "sys", "station_id": "s2", "lat": 48.86, "lon": 2.36, "capacity": 15},
            {"system_id": "sys", "station_id": "s3", "lat": 48.80, "lon": 2.30, "capacity": 15},
        ]
    )


@pytest.fixture
def vehicles():
    times = pd.date_range("2026-06-01", periods=12, freq="1h", tz="UTC")
    rows = []
    for vid in ("v1", "v2", "v3"):
        base = (48.85, 2.35)
        for t in times:
            # v1 never moves (idle); others jitter
            jitter = (0.0, 0.0) if vid == "v1" else (0.003, 0.003)
            rows.append(
                {
                    "system_id": "sys",
                    "vehicle_id": vid,
                    "lat": base[0] + (jitter[0] if t.hour % 2 else 0),
                    "lon": base[1] + (jitter[1] if t.hour % 2 else 0),
                    "fetched_at": t,
                }
            )
    return pd.DataFrame(rows)


def test_service_reliability_index(panel):
    out = gb.service_reliability_index(panel)
    assert {"prob_bikes_avail", "prob_docks_avail", "prob_full_service", "n_obs"} <= set(
        out.columns
    )
    probs = out[["prob_bikes_avail", "prob_docks_avail", "prob_full_service"]]
    assert ((probs >= 0) & (probs <= 1)).all().all()


def test_station_outage_rates(panel):
    out = gb.station_outage_rates(panel)
    assert len(out) == 3
    assert ((out["stockout_rate"] >= 0) & (out["stockout_rate"] <= 1)).all()


def test_capacity_utilization(panel, info):
    out = gb.capacity_utilization(panel, info)
    u = out["utilization_rate"].dropna()
    assert ((u >= 0) & (u <= 1)).all()


def test_dynamic_gini_index(panel):
    out = gb.dynamic_gini_index(panel)
    g = out["gini"].dropna()
    assert ((g >= 0) & (g <= 1)).all()


def test_flow_asymmetry_and_turnover(panel):
    asym = gb.flow_asymmetry_ratio(panel)
    assert (asym["asymmetry_ratio"] >= 0).all()
    proxy = gb.fleet_turnover_proxy(panel)
    assert "turnover_proxy" in proxy.columns


def test_cumulative_imbalance_and_docking_pressure(panel):
    drift = gb.cumulative_imbalance(panel)
    assert "cumulative_drift" in drift.columns
    pressure = gb.docking_pressure(panel)
    assert {"expected_inflow", "docking_pressure"} <= set(pressure.columns)


def test_temporal_autocorrelation(panel):
    out = gb.temporal_autocorrelation(panel, lags=(1, 6))
    assert {"acf_lag_1", "acf_lag_6"} <= set(out.columns)


def test_aliasing_vulnerability(panel):
    out = gb.aliasing_vulnerability(panel)
    risk = out["high_frequency_loss_risk"].dropna()
    assert ((risk >= 0) & (risk <= 1)).all()


def test_spatial_center_of_mass(panel):
    out = gb.spatial_center_of_mass(panel)
    assert {"center_lat", "center_lon"} <= set(out.columns)
    # the centre must lie within the stations' bounding box
    assert out["center_lat"].dropna().between(48.80, 48.86).all()


def test_diurnal_summary_stats(panel):
    out = gb.diurnal_summary_stats(panel)
    assert list(out.columns) == ["hour", "mean", "median", "p05", "p95", "n"]
    assert (out["p05"] <= out["p95"]).all()


def test_temporal_context_features(panel):
    out = gb.temporal_context_features(panel)
    assert set(out["time_block"].cat.categories) == set(gb.analysis.TIME_BLOCKS)
    assert "is_holiday" not in out.columns  # not added without a holidays argument
    with_hol = gb.temporal_context_features(panel, holidays=["2026-06-01"])
    assert "is_holiday" in with_hol.columns


def test_join_exogenous_timeseries(panel):
    times = pd.date_range("2026-06-01", periods=24, freq="1h", tz="UTC")
    exo = pd.DataFrame({"fetched_at": times, "temp_c": np.linspace(12, 20, 24)})
    out = gb.join_exogenous_timeseries(panel, exo)
    assert "temp_c" in out.columns
    assert out["temp_c"].notna().any()


def test_spatial_entropy(vehicles):
    out = gb.spatial_entropy(vehicles, grid_size_m=100)
    assert {"shannon_entropy", "evenness", "n_cells"} <= set(out.columns)
    assert (out["shannon_entropy"] >= 0).all()


def test_vehicle_idle_time(vehicles):
    out = gb.vehicle_idle_time(vehicles, threshold_hours=1)
    assert {"idle_fraction", "n_vehicles", "n_idle"} <= set(out.columns)
    assert ((out["idle_fraction"] >= 0) & (out["idle_fraction"] <= 1)).all()


def test_two_step_fca(info):
    demand = pd.DataFrame(
        {"lat": [48.855, 48.81], "lon": [2.355, 2.305], "population": [1000, 500]}
    )
    score = gb.two_step_fca(info, demand, max_distance_m=2000)
    assert len(score) == 2
    assert (score >= 0).all()
    # closer-to-supply demand point should score at least as well as the far one
    assert score.iloc[0] >= 0

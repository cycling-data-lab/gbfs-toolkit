"""Tests for the flow simulator + empirical compiler (gbfs_toolkit.sim)."""

import json

import numpy as np
import pandas as pd

import gbfs_toolkit as gb
from gbfs_toolkit.core.models import coerce_schema, validate_schema


def test_flows_mass_conserved_and_canonical():
    cfg = gb.SimConfig(
        n_stations=60, days=4, ghost_rate=0.08, weather_events=2, topography=True, seed=1
    )
    info, status, extras = gb.simulate_city_flows(cfg, return_extras=True)
    assert extras["mass_conservation_error"] < 1e-6  # strict conservation
    validate_schema(coerce_schema(status, "station_status"), "station_status")
    assert (info["ghost_bikes"] > 0).any()  # ghost bikes injected


def test_injected_geometry_is_used():
    lat = np.array([48.85, 48.86, 48.87, 48.84])
    lon = np.array([2.35, 2.36, 2.34, 2.33])
    cap = np.array([20, 30, 15, 25], dtype=float)
    role = np.array([0, 1, 2, 0])
    info, _ = gb.simulate_city_flows(
        gb.SimConfig(days=2, inject_lat=lat, inject_lon=lon, inject_capacity=cap, inject_role=role)
    )
    assert np.allclose(np.sort(info["lat"].to_numpy()), np.sort(lat))
    assert info.shape[0] == 4


def test_parquet_export_roundtrips(tmp_path):
    cfg = gb.SimConfig(n_stations=40, days=2, ghost_rate=0.08, scraper_cell_nan=0.02, seed=2)
    path = str(tmp_path / "city.parquet")
    out = gb.generate_gbfs_parquet(cfg, path)
    assert out["rows"] > 0
    df = pd.read_parquet(path)
    df["station_id"] = df["station_id"].astype(str)
    validate_schema(coerce_schema(df, "station_status"), "station_status")
    assert "num_bikes_disabled" in df.columns and df["num_bikes_disabled"].sum() > 0


def test_ml_dataset_export(tmp_path):
    cfg = gb.SimConfig(n_stations=40, days=3, scraper_cell_nan=0.02, seed=3)
    meta = gb.export_ml_dataset(cfg, str(tmp_path))
    assert meta["N"] == 40 and meta["T"] > 0
    bikes = pd.read_parquet(tmp_path / "bikes_available.parquet")
    mask = pd.read_parquet(tmp_path / "observation_mask.parquet")
    assert bikes.shape == mask.shape
    assert bool((mask.to_numpy() == bikes.notna().to_numpy()).all())  # mask = the NaN pattern
    geom = np.load(tmp_path / "graph_geometry.npz")
    assert geom["eigenvectors"].shape[0] == 40
    with open(tmp_path / "splits.json") as f:
        json.load(f)


def test_compiler_fits_a_known_city():
    truth = gb.SimConfig(
        n_stations=50, days=3, beta_km=2.0, base_demand=0.4, trip_rate=10.0, seed=5
    )
    _info, status = gb.simulate_city_flows(truth)
    target = gb.compute_footprint(status)
    out = gb.calibrate_city(_info, target, days=2)
    assert set(out["best_params"]) == {"beta_km", "base_demand", "trip_rate"}
    assert np.isfinite(out["mse"]) and out["mse"] < 1.0  # the twin reproduces the footprint

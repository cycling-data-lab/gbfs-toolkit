"""Tests for the synthetic city generator (interfaces.synthetic)."""

import pandas as pd

import gbfs_toolkit as gb
from gbfs_toolkit.core.models import validate_schema


def test_returns_canonical_frames():
    info, status = gb.simulate_city(n_stations=40, days=3, seed=0)
    # canonical schemas (raises if not)
    validate_schema(info, "station_info")
    validate_schema(status, "station_status")
    assert info.shape[0] == 40
    assert set(["lat", "lon", "capacity"]).issubset(info.columns)
    assert {"num_bikes_available", "fetched_at", "station_id"}.issubset(status.columns)


def test_panel_pivots_to_time_by_station():
    info, status = gb.simulate_city(n_stations=25, days=2, freq="1h", seed=1)
    wide = gb.to_wide_matrix(status)
    assert wide.shape == (2 * 24, 25)
    assert list(wide.columns) == sorted(wide.columns)  # stable station order


def test_availability_within_capacity():
    info, status = gb.simulate_city(n_stations=30, days=2, seed=2)
    total = status["num_bikes_available"] + status["num_docks_available"]
    assert (status["num_bikes_available"] >= 0).all()
    assert (status["num_bikes_available"] <= total).all()


def test_deterministic_under_seed():
    a, _ = gb.simulate_city(n_stations=15, days=1, seed=7)
    b, _ = gb.simulate_city(n_stations=15, days=1, seed=7)
    pd.testing.assert_frame_equal(a, b)


def test_frozen_injection_is_detectable():
    info, status = gb.simulate_city(n_stations=30, days=4, n_frozen=3, seed=3)
    flagged = gb.detect_frozen_stations(status, min_run_hours=24)
    # at least the injected frozen stations should surface
    assert flagged.shape[0] >= 3


def test_od_driven_lowers_synchrony():
    import numpy as np

    def synchrony(od):
        info, status = gb.simulate_city(n_stations=150, days=7, od_driven=od, seed=4)
        wide = gb.to_wide_matrix(status)
        idx = info.set_index("station_id").loc[wide.columns]
        occ = np.clip(wide.to_numpy(float) / idx["capacity"].to_numpy(float)[None, :], 0, 1)
        C = np.corrcoef(occ.T)
        return float(np.nanmean(C[np.triu_indices(occ.shape[1], 1)]))

    # the mass-conserving flow decorrelates stations (one empties as another fills)
    assert synchrony(True) < synchrony(False)
    validate_schema(gb.simulate_city(n_stations=40, days=2, od_driven=True, seed=0)[1], "station_status")


def test_spatial_lowfreq_knob_controls_spectrum():
    import numpy as np

    def lowfreq_share(lf):
        info, status = gb.simulate_city(n_stations=160, days=3, spatial_lowfreq=lf, seed=5)
        wide = gb.to_wide_matrix(status)
        idx = info.set_index("station_id").loc[wide.columns]
        L = gb.normalized_laplacian(gb.knn_adjacency(idx["lat"], idx["lon"], k=8))
        basis = gb.low_freq_basis(L, 16)
        M = wide.to_numpy(float)
        m = M.mean(axis=0)
        # the demand deviation field (where the spatial knob lives) over time
        return float(np.mean([gb.spectral_projection_r2(M[t] - m, basis) for t in range(M.shape[0])]))

    # a smooth (low-frequency) city concentrates more deviation energy in the bottom modes
    assert lowfreq_share(0.9) > lowfreq_share(0.1) + 0.1

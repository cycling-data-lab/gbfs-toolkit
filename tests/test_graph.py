"""Tests for the graph-signal primitives (spatial.graph)."""

import numpy as np

import gbfs_toolkit as gb


def _city_graph(n=120, seed=0):
    info, _ = gb.simulate_city(n_stations=n, days=1, seed=seed)
    W = gb.knn_adjacency(info["lat"], info["lon"], k=8)
    return info, W


def test_adjacency_symmetric_and_laplacian_psd():
    _, W = _city_graph()
    assert np.allclose(W, W.T)
    L = gb.normalized_laplacian(W)
    evals = np.linalg.eigvalsh(L)
    assert evals.min() > -1e-8           # PSD
    assert evals.max() < 2 + 1e-6        # normalised Laplacian spectrum in [0, 2]


def test_rewire_preserves_degree():
    _, W = _city_graph()
    A = (W > 0).astype(int)
    R = gb.degree_preserving_rewire(W, seed=1)
    assert np.array_equal(A.sum(axis=1), R.sum(axis=1))   # degree sequence preserved
    assert np.allclose(R, R.T)
    assert not np.array_equal(A, R)                        # something actually moved


def test_permute_signal_is_a_permutation():
    y = np.arange(50.0)
    p = gb.permute_signal(y, seed=3)
    assert np.array_equal(np.sort(p), np.sort(y))


def test_band_limited_signal_hits_target():
    _, W = _city_graph(n=150, seed=2)
    L = gb.normalized_laplacian(W)
    basis = gb.low_freq_basis(L, 16)
    for target in (0.2, 0.8):
        y = gb.band_limited_signal(L, r2_target=target, n_low=16, seed=4)
        got = gb.spectral_projection_r2(y, basis)
        assert abs(got - target) < 0.08

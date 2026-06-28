"""Graph-signal primitives for spectral methods: a k-NN Laplacian, null models and
band-limited signal synthesis.

These are the reusable pieces behind the program's spectral bounds. A station network
becomes a weighted k-NN graph; its symmetric normalised Laplacian has an eigenbasis in
which a target signal has a spectral profile; the projection R-squared of the signal onto
the low-frequency subspace is the quantity the bounds turn on. The null models
(degree-preserving rewiring, signal permutation) and the controlled-spectrum signal
generator are what let a spectral result be tested against a null and calibrated, rather
than merely asserted.
"""

from __future__ import annotations

import numpy as np
from scipy.linalg import eigh

from gbfs_toolkit.spatial.geometry import GeoKDTree

__all__ = [
    "knn_adjacency",
    "normalized_laplacian",
    "low_freq_basis",
    "spectral_projection_r2",
    "degree_preserving_rewire",
    "permute_signal",
    "band_limited_signal",
]


def knn_adjacency(lat, lon, *, k: int = 10, gaussian: bool = True) -> np.ndarray:
    """Symmetric weighted k-NN adjacency over lat/lon, great-circle distances (metres).

    Edges use a Gaussian kernel at the local median distance when ``gaussian`` (else binary).
    """
    lat = np.asarray(lat, float)
    lon = np.asarray(lon, float)
    n = lat.size
    tree = GeoKDTree(lat, lon)
    dist, idx = tree.query(lat, lon, k=k + 1)  # self in column 0
    sigma = float(np.median(dist[:, 1:])) or 1.0
    W = np.zeros((n, n))
    for i in range(n):
        for d, j in zip(dist[i, 1:], idx[i, 1:], strict=False):
            w = np.exp(-(d**2) / (2 * sigma**2)) if gaussian else 1.0
            W[i, j] = max(W[i, j], w)
    return np.maximum(W, W.T)


def normalized_laplacian(W: np.ndarray) -> np.ndarray:
    """Symmetric normalised Laplacian ``I - D^-1/2 W D^-1/2`` of a weighted adjacency."""
    deg = np.asarray(W).sum(axis=1)
    dinv = 1.0 / np.sqrt(np.maximum(deg, 1e-12))
    return np.eye(W.shape[0]) - (dinv[:, None] * W * dinv[None, :])


def low_freq_basis(L: np.ndarray, d: int) -> np.ndarray:
    """The ``d`` lowest-frequency Laplacian eigenvectors, trivial constant mode excluded."""
    w, V = eigh(L)
    order = np.argsort(w)
    d = int(min(d, L.shape[0] - 1))
    return V[:, order[1 : d + 1]]


def spectral_projection_r2(y, basis: np.ndarray) -> float:
    """R2_spec: fraction of the centred signal variance captured by ``basis`` (orthonormal)."""
    y = np.asarray(y, float)
    y = y - np.nanmean(y)
    y = np.nan_to_num(y)
    denom = float(y @ y)
    if denom < 1e-12:
        return 0.0
    c = basis.T @ y
    return float(c @ c) / denom


def degree_preserving_rewire(
    W: np.ndarray, *, n_swaps: int | None = None, seed: int = 42
) -> np.ndarray:
    """Maslov-Sneppen double-edge swap: shuffle topology, keep the degree sequence.

    Operates on the binary structure of ``W`` (an edge exists where ``W > 0``). Returns a
    binary symmetric adjacency with the same per-node degree, the standard structural null
    for "is this result graph structure or just degree".
    """
    rng = np.random.default_rng(seed)
    A = (np.asarray(W) > 0).astype(int)
    np.fill_diagonal(A, 0)
    edges = [[int(i), int(j)] for i, j in zip(*np.triu(A, 1).nonzero(), strict=False)]
    m = len(edges)
    if m < 2:
        return A
    n_swaps = int(n_swaps if n_swaps is not None else 10 * m)
    eset = {frozenset(e) for e in edges}
    for _ in range(n_swaps):
        x, y = rng.integers(0, m, 2)
        if x == y:
            continue
        a, b = edges[x]
        c, e = edges[y]
        if rng.random() < 0.5:
            c, e = e, c
        if len({a, b, c, e}) < 4:
            continue
        if frozenset((a, e)) in eset or frozenset((c, b)) in eset:
            continue
        eset.discard(frozenset((a, b)))
        eset.discard(frozenset((c, e)))
        eset.add(frozenset((a, e)))
        eset.add(frozenset((c, b)))
        edges[x] = [a, e]
        edges[y] = [c, b]
    out = np.zeros_like(A)
    for a, b in edges:
        out[a, b] = out[b, a] = 1
    return out


def permute_signal(y, *, seed: int = 42) -> np.ndarray:
    """Permute a signal across nodes: the node-label null on a fixed graph."""
    rng = np.random.default_rng(seed)
    y = np.asarray(y, float).copy()
    return y[rng.permutation(y.size)]


def band_limited_signal(
    L: np.ndarray, *, r2_target: float = 0.8, n_low: int = 16, seed: int = 42
) -> np.ndarray:
    """Synthesise a unit-variance signal whose bottom-``n_low`` spectral share is ``r2_target``.

    Mixes a low-frequency component (bottom ``n_low`` non-trivial eigenvectors) with a
    high-frequency one so that ``spectral_projection_r2(y, low_freq_basis(L, n_low))`` is
    approximately ``r2_target``. Use it to calibrate a spectral bound or to build adversarial
    high-frequency targets (``r2_target`` near 0) where the floor must be near zero.
    """
    rng = np.random.default_rng(seed)
    w, V = eigh(L)
    order = np.argsort(w)
    V = V[:, order]
    n = L.shape[0]
    n_low = int(min(n_low, n - 1))
    low = V[:, 1 : n_low + 1] @ rng.normal(0, 1, n_low)
    high = V[:, n_low + 1 :] @ rng.normal(0, 1, max(n - n_low - 1, 1))
    low /= np.linalg.norm(low) + 1e-12
    high /= np.linalg.norm(high) + 1e-12
    r = float(np.clip(r2_target, 0.0, 1.0))
    y = np.sqrt(r) * low + np.sqrt(1 - r) * high
    return (y - y.mean()) / (y.std() + 1e-12)

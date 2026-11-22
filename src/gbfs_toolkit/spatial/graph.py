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

    Parameters
    ----------
    lat, lon : array-like
        Station coordinates in degrees (EPSG:4326).
    k : int, default 10
        Neighbours per station (capped at ``n - 1``); the graph is symmetrised, so a
        station can end up with more than ``k`` edges.
    gaussian : bool, default True
        Weight ``exp(-d^2 / (2 sigma^2))`` with ``sigma`` the median k-NN distance; if
        ``False``, every edge weighs 1.

    Returns
    -------
    numpy.ndarray
        The ``(n, n)`` symmetric adjacency, zero diagonal.

    Examples
    --------
    >>> import numpy as np
    >>> lat = 43.6 + np.arange(6) * 0.003
    >>> lon = np.full(6, 3.87)
    >>> W = knn_adjacency(lat, lon, k=2)
    >>> W.shape, bool(np.allclose(W, W.T)), float(W.diagonal().max())
    ((6, 6), True, 0.0)
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
    """Symmetric normalised Laplacian ``I - D^-1/2 W D^-1/2`` of a weighted adjacency.

    Isolated nodes (zero degree) get a unit diagonal and no off-diagonal terms.

    Examples
    --------
    >>> import numpy as np
    >>> W = np.array([[0.0, 1.0], [1.0, 0.0]])
    >>> normalized_laplacian(W).tolist()
    [[1.0, -1.0], [-1.0, 1.0]]
    """
    deg = np.asarray(W).sum(axis=1)
    dinv = 1.0 / np.sqrt(np.maximum(deg, 1e-12))
    return np.eye(W.shape[0]) - (dinv[:, None] * W * dinv[None, :])


def low_freq_basis(L: np.ndarray, d: int) -> np.ndarray:
    """The ``d`` lowest-frequency Laplacian eigenvectors, trivial constant mode excluded.

    Returns an ``(n, d)`` orthonormal basis (``d`` capped at ``n - 1``), the subspace
    [`spectral_projection_r2`][gbfs_toolkit.spectral_projection_r2] projects onto.

    Examples
    --------
    >>> import numpy as np
    >>> W = np.ones((4, 4)) - np.eye(4)
    >>> B = low_freq_basis(normalized_laplacian(W), 2)
    >>> B.shape, bool(np.allclose(B.T @ B, np.eye(2)))
    ((4, 2), True)
    """
    w, V = eigh(L)
    order = np.argsort(w)
    d = int(min(d, L.shape[0] - 1))
    return V[:, order[1 : d + 1]]


def spectral_projection_r2(y, basis: np.ndarray) -> float:
    """R2_spec: fraction of the centred signal variance captured by ``basis`` (orthonormal).

    The signal is centred, ``NaN`` entries count as the mean, and a constant signal
    returns ``0.0``. The result lies in ``[0, 1]``.

    Examples
    --------
    >>> import numpy as np
    >>> basis = np.array([[1.0], [-1.0], [0.0]]) / np.sqrt(2)
    >>> round(spectral_projection_r2([1.0, -1.0, 0.0], basis), 6)
    1.0
    """
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
    for "is this result graph structure or just degree". Seeded, so reproducible.

    Examples
    --------
    >>> import numpy as np
    >>> W = (np.add.outer(np.arange(8), np.arange(8)) % 3 == 0).astype(float)
    >>> np.fill_diagonal(W, 0)
    >>> R = degree_preserving_rewire(W, seed=0)
    >>> bool((R.sum(axis=1) == (W > 0).sum(axis=1)).all())
    True
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
    """Permute a signal across nodes: the node-label null on a fixed graph.

    Examples
    --------
    >>> sorted(permute_signal([3, 1, 2], seed=0).tolist())
    [1.0, 2.0, 3.0]
    """
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

    Examples
    --------
    >>> import numpy as np
    >>> lat = 43.6 + np.arange(12) * 0.003
    >>> lon = 3.87 + (np.arange(12) % 4) * 0.004
    >>> L = normalized_laplacian(knn_adjacency(lat, lon, k=3))
    >>> y = band_limited_signal(L, r2_target=0.7, n_low=3, seed=0)
    >>> round(spectral_projection_r2(y, low_freq_basis(L, 3)), 2)
    0.7
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

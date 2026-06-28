"""Inter-rater agreement and proportion intervals for human-validation studies.

Pure, dependency-light implementations of the coefficients an audit needs when a
panel re-labels a sample by hand: Krippendorff's nominal alpha (handles missing
ratings and >2 raters), Cohen's kappa (two raters) and the Wilson score interval
for a proportion. No heuristics, no I/O.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd


def wilson_interval(successes: int, n: int, *, z: float = 1.959963984540054) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion (default 95%).

    More reliable than the normal approximation for small ``n`` or extreme rates,
    and it never leaves ``[0, 1]``.

    Examples
    --------
    >>> tuple(round(x, 3) for x in wilson_interval(8, 10))
    (0.49, 0.943)
    """
    if n == 0:
        return (float("nan"), float("nan"))
    p = successes / n
    z2 = z * z
    denom = 1 + z2 / n
    center = (p + z2 / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def cohen_kappa(a, b) -> float:
    """Cohen's kappa between two raters over paired nominal labels.

    Pairs with a missing label in either rater are dropped.

    Examples
    --------
    >>> cohen_kappa([1, 2, 3, 1], [1, 2, 3, 1])  # perfect agreement
    1.0
    """
    sa = pd.Series(list(a)).reset_index(drop=True)
    sb = pd.Series(list(b)).reset_index(drop=True)
    keep = sa.notna() & sb.notna()
    sa, sb = sa[keep], sb[keep]
    n = len(sa)
    if n == 0:
        return float("nan")
    po = float((sa.to_numpy() == sb.to_numpy()).mean())
    cats = pd.Index(sorted(set(sa) | set(sb)))
    pa = sa.value_counts(normalize=True).reindex(cats).fillna(0.0)
    pb = sb.value_counts(normalize=True).reindex(cats).fillna(0.0)
    pe = float((pa * pb).sum())
    if pe >= 1.0:
        return 1.0
    return (po - pe) / (1 - pe)


def krippendorff_alpha(reliability_data, *, missing=np.nan) -> float:
    """Krippendorff's alpha for nominal data.

    Parameters
    ----------
    reliability_data : 2D array-like
        Shape ``(n_raters, n_units)``; entry ``[r, u]`` is rater ``r``'s label for
        unit ``u``, or ``missing`` where that rater did not label that unit.
    missing : value, default ``nan``
        Sentinel for an absent rating.

    Returns
    -------
    float
        ``1`` = perfect agreement, ``0`` = chance, ``< 0`` = systematic
        disagreement. ``nan`` if fewer than one pairable unit.

    Examples
    --------
    Two raters, three units, identical labels (rows are raters, columns units):

    >>> krippendorff_alpha([[1, 2, 1], [1, 2, 1]])
    1.0
    """
    data = np.asarray(reliability_data, dtype=object)

    def _is_missing(v) -> bool:
        if v is missing:
            return True
        try:
            return isinstance(v, float) and math.isnan(v)
        except TypeError:
            return False

    # Coincidence matrix over labels that share a unit with >= 2 ratings.
    coincidence: dict[tuple, float] = {}
    n_pairable = 0.0
    for u in range(data.shape[1]):
        vals = [v for v in data[:, u] if not _is_missing(v)]
        m = len(vals)
        if m < 2:
            continue
        n_pairable += m
        w = 1.0 / (m - 1)
        for i in range(m):
            for j in range(m):
                if i == j:
                    continue
                key = (vals[i], vals[j])
                coincidence[key] = coincidence.get(key, 0.0) + w
    if n_pairable < 2:
        return float("nan")

    labels = sorted({c for pair in coincidence for c in pair}, key=repr)
    n_c = dict.fromkeys(labels, 0.0)
    for (c, _k), o in coincidence.items():
        n_c[c] += o
    n = sum(n_c.values())
    diag = sum(coincidence.get((c, c), 0.0) for c in labels)
    sum_nc2 = sum(v * v for v in n_c.values())
    expected = n * n - sum_nc2
    if expected == 0:
        return 1.0
    return 1.0 - (n - 1) * (n - diag) / expected

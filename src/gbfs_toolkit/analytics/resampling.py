"""Resampling and effective-sample-size tools for autocorrelated availability series.

Bike availability at 8:00 is highly correlated with 8:05; a naive i.i.d. bootstrap
or a raw n then badly understate uncertainty. These give an honest interval and an
honest sample size for dependent data, so reported confidence bounds survive review.
"""
from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd


def effective_sample_size(series) -> float:
    """Autocorrelation-adjusted effective sample size of a 1-D series.

    ``ESS = n / (1 + 2 * sum_k rho_k)`` over Geyer's initial positive sequence of the
    autocorrelations. A strongly autocorrelated series of length ``n`` carries far
    fewer than ``n`` independent observations; ESS is the count to use in an analytic
    standard error.
    """
    x = np.asarray(series, dtype="float64")
    x = x[np.isfinite(x)]
    n = x.size
    if n < 2:
        return float(n)
    x = x - x.mean()
    denom = float((x**2).sum())
    if denom == 0:
        return float(n)
    acf_full = np.correlate(x, x, mode="full")[n - 1 :]
    acf = acf_full / acf_full[0]
    s = 0.0
    for k in range(1, n):
        if acf[k] <= 0:  # initial positive sequence
            break
        s += acf[k]
    ess = n / (1.0 + 2.0 * s)
    return float(min(max(ess, 1.0), n))


def block_bootstrap_ci(
    series,
    *,
    statistic: Callable = np.mean,
    block_size: int | None = None,
    n_boot: int = 2000,
    alpha: float = 0.05,
    seed: int = 42,
) -> pd.Series:
    """Moving-block bootstrap confidence interval for a statistic of a dependent series.

    Resamples contiguous blocks (not individual points) so the within-block
    autocorrelation is preserved, the way to bootstrap a time series. The default
    block size is ``n**(1/3)`` (the standard rate). Seeded, hence reproducible.

    Returns
    -------
    pandas.Series
        ``{estimate, ci_lo, ci_hi}`` at the central ``1 - alpha`` level.

    References
    ----------
    Lahiri (2003). *Resampling Methods for Dependent Data*. Springer.
    """
    x = np.asarray(series, dtype="float64")
    x = x[np.isfinite(x)]
    n = x.size
    if n == 0:
        return pd.Series({"estimate": float("nan"), "ci_lo": float("nan"), "ci_hi": float("nan")})
    if block_size is None:
        block_size = max(1, int(round(n ** (1 / 3))))
    block_size = min(block_size, n)
    n_blocks = int(np.ceil(n / block_size))
    starts_max = n - block_size + 1
    rng = np.random.default_rng(seed)
    boots = np.empty(n_boot)
    for b in range(n_boot):
        starts = rng.integers(0, starts_max, size=n_blocks)
        sample = np.concatenate([x[s : s + block_size] for s in starts])[:n]
        boots[b] = statistic(sample)
    lo, hi = np.percentile(boots, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return pd.Series(
        {"estimate": float(statistic(x)), "ci_lo": float(lo), "ci_hi": float(hi)}
    )

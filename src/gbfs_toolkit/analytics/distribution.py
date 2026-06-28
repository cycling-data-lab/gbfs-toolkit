"""Inequality and system profiles: concentration, Lorenz/Gini/Theil, dynamic equity.

Strictly **descriptive** summaries of canonical frames: no OD/trip inference, no prediction.
All functions are pure and pandas-only. Exposed on the ``.gbfs`` accessor.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from gbfs_toolkit.analytics.frames import STATION_STATES, station_state
from gbfs_toolkit.core.models import require_columns
from gbfs_toolkit.core.utils import gini, num


def system_profile(availability: pd.DataFrame) -> pd.Series:
    """A one-glance numeric profile of one availability snapshot: the bikeshare ``describe()``.

    Parameters
    ----------
    availability : pandas.DataFrame
        An availability frame (e.g. from :func:`~gbfs_toolkit.join_availability`): needs
        ``num_bikes_available`` / ``num_docks_available``; uses ``capacity``, ``station_type``,
        ``is_virtual_station``, ``is_renting`` / ``is_returning``, ``fetched_at`` /
        ``last_reported`` when present.

    Returns
    -------
    pandas.Series
        Counts and rates: ``n_stations``, ``total_capacity``, ``total_bikes_available``,
        ``total_docks_available``, ``mean_occupancy``, ``pct_<state>`` for each
        :data:`~gbfs_toolkit.analytics.frames.STATION_STATES`, and ``staleness_min_median``.

    See Also
    --------
    [`compare_systems`][gbfs_toolkit.compare_systems] : Stack this profile across many systems.
    [`concentration_metrics`][gbfs_toolkit.concentration_metrics] : Inequality of capacity behind the profile.

    Examples
    --------
    >>> import pandas as pd
    >>> av = pd.DataFrame({
    ...     "system_id": "s", "station_id": ["a", "b"], "capacity": [20, 20],
    ...     "num_bikes_available": [5, 15], "num_docks_available": [15, 5],
    ... })
    >>> int(system_profile(av)["n_stations"])
    2
    """
    df = availability
    bikes, docks = num(df, "num_bikes_available"), num(df, "num_docks_available")
    out: dict[str, float] = {"n_stations": int(len(df))}
    if "capacity" in df.columns:
        out["total_capacity"] = float(num(df, "capacity").sum())
    out["total_bikes_available"] = float(bikes.sum())
    out["total_docks_available"] = float(docks.sum())

    denom = bikes + docks
    occ = (bikes / denom).where(denom > 0)
    out["mean_occupancy"] = round(float(occ.mean()), 4) if occ.notna().any() else float("nan")

    if len(df):
        states = station_state(df).value_counts(normalize=True)
        for s in STATION_STATES:
            out[f"pct_{s}"] = round(float(states.get(s, 0.0)), 4)

    if "fetched_at" in df.columns and "last_reported" in df.columns:
        lag = (
            pd.to_datetime(df["fetched_at"], utc=True)
            - pd.to_datetime(df["last_reported"], utc=True)
        ).dt.total_seconds() / 60
        if lag.notna().any():
            out["staleness_min_median"] = round(float(lag.median()), 1)
    return pd.Series(out)


def compare_systems(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Stack :func:`system_profile` across many systems into a comparison table.

    Parameters
    ----------
    frames : dict of str -> pandas.DataFrame
        ``{system_id: availability_frame}`` (e.g. built from
        :func:`~gbfs_toolkit.fetch_multiple`).

    Returns
    -------
    pandas.DataFrame
        One row per system (index ``system_id``), one column per profile metric.

    See Also
    --------
    [`system_profile`][gbfs_toolkit.system_profile] : The per-system profile this stacks.
    [`concentration_metrics`][gbfs_toolkit.concentration_metrics] : Add an inequality lens per system.

    Examples
    --------
    >>> import pandas as pd
    >>> a = pd.DataFrame({"num_bikes_available": [5], "num_docks_available": [5]})
    >>> b = pd.DataFrame({"num_bikes_available": [2], "num_docks_available": [8]})
    >>> compare_systems({"sys_a": a, "sys_b": b}).index.tolist()
    ['sys_a', 'sys_b']
    """
    rows = {sid: system_profile(av) for sid, av in frames.items()}
    out = pd.DataFrame(rows).T
    out.index.name = "system_id"
    return out


def _theil(x: np.ndarray) -> float:
    """Theil T index of a positive array (0 = equal; decomposable alternative to Gini)."""
    x = x[np.isfinite(x) & (x > 0)]
    if x.size == 0:
        return float("nan")
    mu = x.mean()
    if mu == 0:
        return float("nan")
    r = x / mu
    return float(np.mean(r * np.log(r)))


def theil_index(values, *, groups=None):
    """Theil's T inequality index, optionally decomposed between and within groups.

    Theil, unlike the Gini, is additively decomposable: with a group label per value
    it splits total inequality into a *between-group* term (e.g. centre versus
    periphery) and a *within-group* term, so a researcher can attribute service
    inequality to the right spatial scale. Bring your own group column (BYOD).

    Parameters
    ----------
    values : array-like
        Non-negative quantities (capacity, available bikes, ...); non-positive
        entries are dropped (``ln`` is undefined at 0).
    groups : array-like, optional
        Group label per value. When given, returns the decomposition.

    Returns
    -------
    float or pandas.Series
        The scalar Theil T, or a Series ``{total, between, within}`` (``total ==
        between + within``).

    See Also
    --------
    [`palma_ratio`][gbfs_toolkit.palma_ratio] : A tail-sensitive inequality alternative.
    [`concentration_metrics`][gbfs_toolkit.concentration_metrics] : Gini + Theil + top-decile share in one call.
    [`dynamic_gini_index`][gbfs_toolkit.dynamic_gini_index] : The same inequality over time.

    Examples
    --------
    >>> round(float(theil_index([1, 1, 10, 10])), 3)
    0.389
    >>> theil_index([5, 5, 5, 5])  # perfect equality
    0.0
    """
    x = np.asarray(values, dtype="float64")
    if groups is None:
        return _theil(x)
    g = np.asarray(groups)
    mask = np.isfinite(x) & (x > 0)
    x, g = x[mask], g[mask]
    if x.size == 0:
        return pd.Series({"total": float("nan"), "between": float("nan"), "within": float("nan")})
    n = x.size
    grand = x.sum()
    between = 0.0
    within = 0.0
    for grp in pd.unique(g):
        xs = x[g == grp]
        s = xs.sum() / grand  # share of total quantity
        p = xs.size / n  # share of population
        if s > 0 and p > 0:
            between += s * np.log(s / p)
        within += s * _theil(xs)
    return pd.Series({"total": between + within, "between": between, "within": within})


def palma_ratio(values) -> float:
    """Palma ratio: the top-10% share over the bottom-40% share.

    The modern measure of *extreme* inequality, more sensitive than the Gini to the
    tails: the total quantity held by the best-served 10% of stations divided by
    that of the least-served 40%.

    See Also
    --------
    [`theil_index`][gbfs_toolkit.theil_index] : A decomposable inequality alternative.
    [`concentration_metrics`][gbfs_toolkit.concentration_metrics] : Gini + Theil + top-decile share in one call.

    Examples
    --------
    >>> round(palma_ratio(list(range(1, 11))), 1)
    1.0
    """
    x = np.sort(np.asarray(values, dtype="float64"))
    x = x[np.isfinite(x)]
    n = x.size
    if n == 0 or x.sum() == 0:
        return float("nan")
    bottom40 = x[: int(np.floor(0.4 * n))].sum()
    top10 = x[int(np.ceil(0.9 * n)) :].sum()
    if bottom40 <= 0:
        return float("inf")
    return float(top10 / bottom40)


def concentration_metrics(info: pd.DataFrame, *, value_col: str = "capacity") -> pd.Series:
    """How concentrated is capacity across stations? An equity / coverage lens.

    Reports the **Gini coefficient** and **Theil T index** of ``value_col`` and the share held
    by the top decile of stations (a system can claim wide coverage yet stash most bikes in a
    few central hubs). Deliberately *outside* the published A1–A7 audit taxonomy; these are
    descriptive metrics, not a feed-quality verdict. See :func:`lorenz_curve` for the curve.

    Returns
    -------
    pandas.Series
        ``n_stations``, ``total_capacity``, ``gini``, ``theil``, ``top_decile_share``.

    See Also
    --------
    [`lorenz_curve`][gbfs_toolkit.lorenz_curve] : The curve behind these scalars.
    [`theil_index`][gbfs_toolkit.theil_index] : The decomposable Theil index alone.
    [`palma_ratio`][gbfs_toolkit.palma_ratio] : The tail-sensitive Palma ratio alone.
    [`dynamic_gini_index`][gbfs_toolkit.dynamic_gini_index] : The same concentration over time.

    Examples
    --------
    >>> import pandas as pd
    >>> info = pd.DataFrame({"system_id": "s", "station_id": list("abcd"), "capacity": [10, 10, 10, 70]})
    >>> round(float(concentration_metrics(info)["gini"]), 2)
    0.45
    """
    x = num(info, value_col).dropna().to_numpy()
    x = np.sort(x[x > 0])
    out: dict[str, float] = {"n_stations": int(x.size)}
    if x.size == 0:
        out["total_capacity"] = 0.0
        out["gini"] = float("nan")
        out["theil"] = float("nan")
        out["top_decile_share"] = float("nan")
        return pd.Series(out)
    out["total_capacity"] = float(x.sum())
    out["gini"] = round(gini(x), 4)
    out["theil"] = round(_theil(x), 4)
    k = max(1, int(np.ceil(0.1 * x.size)))
    out["top_decile_share"] = round(float(x[-k:].sum() / x.sum()), 4)
    return pd.Series(out)


def lorenz_curve(info: pd.DataFrame, *, value_col: str = "capacity") -> pd.DataFrame:
    """Lorenz-curve points for plotting capacity inequality.

    Returns the cumulative share of stations vs. cumulative share of ``value_col``, starting
    at the origin ``(0, 0)``. The diagonal is perfect equality; the area between it and the
    curve is half the Gini. Pairs with :func:`concentration_metrics`.

    Returns
    -------
    pandas.DataFrame
        ``cum_population_share``, ``cum_value_share`` (both in ``[0, 1]``, ascending).

    See Also
    --------
    [`concentration_metrics`][gbfs_toolkit.concentration_metrics] : The Gini/Theil scalars summarising this curve.
    [`theil_index`][gbfs_toolkit.theil_index] : A decomposable inequality scalar.

    Examples
    --------
    >>> import pandas as pd
    >>> info = pd.DataFrame({"system_id": "s", "station_id": list("abcd"), "capacity": [10, 10, 10, 70]})
    >>> lorenz_curve(info)["cum_value_share"].tolist()
    [0.0, 0.1, 0.2, 0.3, 1.0]
    """
    x = num(info, value_col).dropna().to_numpy()
    x = np.sort(x[x > 0])
    if x.size == 0:
        return pd.DataFrame({"cum_population_share": [0.0], "cum_value_share": [0.0]})
    cum_pop = np.arange(1, x.size + 1) / x.size
    cum_val = np.cumsum(x) / x.sum()
    return pd.DataFrame(
        {
            "cum_population_share": np.concatenate([[0.0], cum_pop]),
            "cum_value_share": np.concatenate([[0.0], cum_val]),
        }
    )


def dynamic_gini_index(
    panel: pd.DataFrame, *, target_col: str = "num_bikes_available", time_col: str = "fetched_at"
) -> pd.DataFrame:
    """Gini coefficient of available bikes across stations, as a time series.

    Capacity-based concentration (see :func:`concentration_metrics`) measures a network's static
    design. This measures the *dynamic* inequality of where the bikes actually are: a system with
    evenly distributed capacity can still become deeply unequal at 18:00, when the fleet piles into
    one district. A rising curve over the day objectifies that loss of equity.

    Parameters
    ----------
    panel : pandas.DataFrame
        From :func:`build_availability_panel` or a flat frame with ``station_id``, ``time_col`` and
        ``target_col``.
    target_col : str, default "num_bikes_available"
        The per-station quantity whose distribution is measured.
    time_col : str, default "fetched_at"
        Snapshot timestamp.

    Returns
    -------
    pandas.DataFrame
        ``<time_col>, gini, n_stations`` (one row per snapshot).

    See Also
    --------
    [`concentration_metrics`][gbfs_toolkit.concentration_metrics] : Static capacity concentration.
    [`temporal_concentration`][gbfs_toolkit.temporal_concentration] : The temporal (per-station) analogue.
    [`theil_index`][gbfs_toolkit.theil_index] : A decomposable inequality scalar.

    Examples
    --------
    >>> import pandas as pd
    >>> panel = pd.DataFrame({
    ...     "station_id": ["a", "b", "a", "b"],
    ...     "fetched_at": pd.to_datetime(
    ...         ["2026-01-01T08:00Z"] * 2 + ["2026-01-01T18:00Z"] * 2),
    ...     "num_bikes_available": [5, 5, 10, 0],
    ... })
    >>> out = dynamic_gini_index(panel)
    >>> bool(out["gini"].iloc[0] < out["gini"].iloc[1])
    True
    """
    df = panel.reset_index() if isinstance(panel.index, pd.MultiIndex) else panel.copy()
    require_columns(df, [time_col, target_col], what="dynamic_gini_index")
    vals = pd.to_numeric(df[target_col], errors="coerce")
    rows = []
    for t, idx in df.groupby(time_col, sort=True).groups.items():
        v = vals.loc[idx].dropna().to_numpy()
        rows.append({time_col: t, "gini": gini(v), "n_stations": int(v.size)})
    return pd.DataFrame(rows)


def format_paper_summary(
    profile: pd.Series | pd.DataFrame, *, fmt: str = "markdown", decimals: int = 2
) -> str:
    """Render a profile as a publication-ready Markdown or LaTeX table.

    Every paper carries a "Table 1: dataset description". Turning the raw output of
    :func:`system_profile` or :func:`compare_systems` into a clean table (rounded floats,
    thousands separators, aligned columns) is a recurring twenty-minute chore. This does
    it in one call. It only formats your own profiling output; it computes nothing new.

    Parameters
    ----------
    profile : pandas.Series or pandas.DataFrame
        A profile, e.g. from :func:`system_profile` (Series) or :func:`compare_systems`
        (DataFrame).
    fmt : {"markdown", "latex"}, default "markdown"
        Output dialect. ``"latex"`` delegates to :meth:`pandas.DataFrame.to_latex`.
    decimals : int, default 2
        Rounding for floating-point cells (thousands separators are added in Markdown).

    Returns
    -------
    str
        The formatted table, ready to paste into a manuscript.

    See Also
    --------
    [`system_profile`][gbfs_toolkit.system_profile] : The single-system profile to format.
    [`compare_systems`][gbfs_toolkit.compare_systems] : The multi-system table to format.

    Examples
    --------
    >>> import pandas as pd
    >>> prof = pd.Series({"n_stations": 100, "mean_occupancy": 0.4123})
    >>> out = format_paper_summary(prof)
    >>> "mean_occupancy" in out and "0.41" in out
    True
    """
    if fmt not in ("markdown", "latex"):
        raise ValueError(f"fmt must be 'markdown' or 'latex', got {fmt!r}")
    obj = profile.to_frame(name="value") if isinstance(profile, pd.Series) else profile.copy()
    obj = obj.round(decimals)

    def _cell(v: object) -> str:
        if isinstance(v, (int, float, np.floating)) and pd.notna(v):
            return f"{v:,.{decimals}f}"
        return str(v)

    header = [str(obj.index.name or ""), *[str(c) for c in obj.columns]]
    body = [[str(idx), *[_cell(v) for v in row]] for idx, row in obj.iterrows()]

    if fmt == "markdown":
        lines = [
            "| " + " | ".join(header) + " |",
            "| " + " | ".join("---" for _ in header) + " |",
            *["| " + " | ".join(r) + " |" for r in body],
        ]
        return "\n".join(lines)

    # LaTeX booktabs table, generated directly so no jinja2 / Styler dependency is needed.
    def _tex(s: str) -> str:
        return (
            s.replace("\\", "\\textbackslash{}")
            .replace("_", r"\_")
            .replace("%", r"\%")
            .replace("&", r"\&")
        )

    align = "l" + "r" * len(obj.columns)
    lines = [
        rf"\begin{{tabular}}{{{align}}}",
        r"\toprule",
        " & ".join(_tex(h) for h in header) + r" \\",
        r"\midrule",
        *[" & ".join(_tex(c) for c in r) + r" \\" for r in body],
        r"\bottomrule",
        r"\end{tabular}",
    ]
    return "\n".join(lines)

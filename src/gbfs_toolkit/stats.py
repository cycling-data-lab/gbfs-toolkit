"""Descriptive statistics — readable summaries of canonical frames.

The plumbing (ingest / audit / panel) turns feeds into tidy data; this module turns tidy
data into the numbers a researcher actually reports. Strictly **descriptive** — no OD/trip
inference, no prediction (those belong in dedicated research code). All functions are pure
and pandas-only.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from gbfs_toolkit.analysis import STATION_STATES, station_state


def _num(df: pd.DataFrame, col: str) -> pd.Series:
    """Numeric view of a column (NaN where absent/unparseable)."""
    if col not in df.columns:
        return pd.Series(np.nan, index=df.index, dtype="float64")
    return pd.to_numeric(df[col], errors="coerce")


def system_profile(availability: pd.DataFrame) -> pd.Series:
    """A one-glance numeric profile of one availability snapshot — the bikeshare ``describe()``.

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
        :data:`~gbfs_toolkit.analysis.STATION_STATES`, and ``staleness_min_median``.
    """
    df = availability
    bikes, docks = _num(df, "num_bikes_available"), _num(df, "num_docks_available")
    out: dict[str, float] = {"n_stations": int(len(df))}
    if "capacity" in df.columns:
        out["total_capacity"] = float(_num(df, "capacity").sum())
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
    """
    rows = {sid: system_profile(av) for sid, av in frames.items()}
    out = pd.DataFrame(rows).T
    out.index.name = "system_id"
    return out


def _gini(x: np.ndarray) -> float:
    """Gini coefficient of a non-negative array (0 = equal, →1 = concentrated)."""
    x = np.sort(x)
    n = x.size
    total = x.sum()
    if n == 0 or total == 0:
        return float("nan")
    idx = np.arange(1, n + 1)
    return float((2 * np.sum(idx * x)) / (n * total) - (n + 1) / n)


def _theil(x: np.ndarray) -> float:
    """Theil T index of a positive array (0 = equal; decomposable alternative to Gini)."""
    mu = x.mean()
    if mu == 0:
        return float("nan")
    r = x / mu
    return float(np.mean(r * np.log(r)))


def concentration_metrics(info: pd.DataFrame, *, value_col: str = "capacity") -> pd.Series:
    """How concentrated is capacity across stations? — an equity / coverage lens.

    Reports the **Gini coefficient** and **Theil T index** of ``value_col`` and the share held
    by the top decile of stations (a system can claim wide coverage yet stash most bikes in a
    few central hubs). Deliberately *outside* the published A1–A7 audit taxonomy — these are
    descriptive metrics, not a feed-quality verdict. See :func:`lorenz_curve` for the curve.

    Returns
    -------
    pandas.Series
        ``n_stations``, ``total_capacity``, ``gini``, ``theil``, ``top_decile_share``.
    """
    x = _num(info, value_col).dropna().to_numpy()
    x = np.sort(x[x > 0])
    out: dict[str, float] = {"n_stations": int(x.size)}
    if x.size == 0:
        out["total_capacity"] = 0.0
        out["gini"] = float("nan")
        out["theil"] = float("nan")
        out["top_decile_share"] = float("nan")
        return pd.Series(out)
    out["total_capacity"] = float(x.sum())
    out["gini"] = round(_gini(x), 4)
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
    """
    x = _num(info, value_col).dropna().to_numpy()
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


def _knn_weights(lat: np.ndarray, lon: np.ndarray, k: int):
    """Row-standardised binary k-nearest-neighbour spatial weights (sparse)."""
    from scipy.sparse import csr_matrix, diags

    from gbfs_toolkit.geo import GeoKDTree

    n = lat.size
    k = min(k, n - 1)
    _, idx = GeoKDTree(lat, lon).query(lat, lon, k=k + 1)  # includes self at col 0
    neighbours = np.asarray(idx)[:, 1 : k + 1]
    rows = np.repeat(np.arange(n), k)
    cols = neighbours.ravel()
    w = csr_matrix((np.ones(rows.size), (rows, cols)), shape=(n, n))
    rowsum = np.asarray(w.sum(axis=1)).ravel()
    rowsum[rowsum == 0] = 1.0
    return diags(1.0 / rowsum) @ w


def morans_i(info: pd.DataFrame, value_col: str, *, k: int = 8) -> pd.Series:
    """Global **Moran's I** — spatial autocorrelation of ``value_col`` across stations.

    Answers "are similar values geographically clustered?" (e.g. are empty/low-occupancy
    stations grouped together — an equity / accessibility signal). Uses row-standardised
    binary k-nearest-neighbour weights; significance is the analytic z-score / p-value under
    the normality assumption. ``I > E[I]`` ⇒ clustering, ``< E[I]`` ⇒ dispersion/checkerboard.

    Returns
    -------
    pandas.Series
        ``morans_i``, ``expected_i`` (= ``-1/(n-1)``), ``z_score``, ``p_value``, ``n``.
    """
    sub = info[["lat", "lon", value_col]].copy()
    for c in ("lat", "lon", value_col):
        sub[c] = pd.to_numeric(sub[c], errors="coerce")
    sub = sub.dropna()
    lat, lon = sub["lat"].to_numpy(), sub["lon"].to_numpy()
    x = sub[value_col].to_numpy(dtype="float64")
    n = x.size
    nan = float("nan")
    if n < 3 or k < 1:
        return pd.Series(
            {"morans_i": nan, "expected_i": nan, "z_score": nan, "p_value": nan, "n": int(n)}
        )

    w = _knn_weights(lat, lon, k)
    z = x - x.mean()
    zz = float((z * z).sum())
    s0 = float(w.sum())
    if zz == 0 or s0 == 0:
        return pd.Series(
            {"morans_i": nan, "expected_i": nan, "z_score": nan, "p_value": nan, "n": int(n)}
        )
    morans = (n / s0) * float(z @ (w @ z)) / zz
    expected = -1.0 / (n - 1)

    wt = w + w.T
    s1 = 0.5 * float(wt.multiply(wt).sum())
    rs = np.asarray(w.sum(axis=1)).ravel()
    cs = np.asarray(w.sum(axis=0)).ravel()
    s2 = float(np.sum((rs + cs) ** 2))
    var = (n * n * s1 - n * s2 + 3 * s0 * s0) / (s0 * s0 * (n * n - 1)) - expected * expected
    if var > 0:
        from scipy.stats import norm

        z_score = (morans - expected) / np.sqrt(var)
        p_value = float(2 * norm.sf(abs(z_score)))
    else:
        z_score = p_value = nan
    return pd.Series(
        {
            "morans_i": round(morans, 4),
            "expected_i": round(expected, 4),
            "z_score": round(float(z_score), 4) if np.isfinite(z_score) else nan,
            "p_value": round(p_value, 4) if np.isfinite(p_value) else nan,
            "n": int(n),
        }
    )


def ripley_k(info: pd.DataFrame, radii: object, *, area_km2: float | None = None) -> pd.DataFrame:
    """**Ripley's K / L** — multi-scale clustering of station locations.

    For each radius, ``K(r)`` is proportional to the mean number of other stations within
    ``r``; ``L(r) = sqrt(K(r)/π) − r`` linearises it: ``L(r) > 0`` ⇒ clustering at scale ``r``,
    ``< 0`` ⇒ dispersion. Density uses the convex hull by default, or ``area_km2`` (e.g. the
    geofencing service area) if given. No edge correction — bias grows near the boundary.

    Parameters
    ----------
    radii : array-like
        Distances in metres at which to evaluate K/L.

    Returns
    -------
    pandas.DataFrame
        ``radius_m``, ``k``, ``l`` (one row per radius).
    """
    lat, lon = _num(info, "lat").to_numpy(), _num(info, "lon").to_numpy()
    finite = np.isfinite(lat) & np.isfinite(lon)
    lat, lon = lat[finite], lon[finite]
    radii = np.asarray(radii, dtype="float64")
    n = lat.size
    if n < 2:
        return pd.DataFrame({"radius_m": radii, "k": np.nan, "l": np.nan})

    area_m2 = (area_km2 * 1e6) if area_km2 is not None else _hull_area_km2(lat, lon) * 1e6
    from gbfs_toolkit.geo import GeoKDTree

    tree = GeoKDTree(lat, lon)
    ks = []
    for r in radii:
        hits = tree.query_radius(lat, lon, radius_m=float(r))
        pairs = sum(len(h) - 1 for h in hits)  # exclude self
        ks.append(area_m2 * pairs / (n * (n - 1)) if np.isfinite(area_m2) else np.nan)
    k_arr = np.asarray(ks)
    l_arr = np.sqrt(k_arr / np.pi) - radii
    return pd.DataFrame({"radius_m": radii, "k": k_arr, "l": l_arr})


_EARTH_RADIUS_M = 6_371_000.0


def _hull_area_km2(lat: np.ndarray, lon: np.ndarray) -> float:
    """Convex-hull area (km²) of points, via an equal-area-ish local projection."""
    from scipy.spatial import ConvexHull, QhullError

    lat_r, lon_r = np.radians(lat), np.radians(lon)
    mean_lat = float(np.mean(lat_r))
    x = _EARTH_RADIUS_M * lon_r * np.cos(mean_lat)
    y = _EARTH_RADIUS_M * lat_r
    try:
        return float(ConvexHull(np.column_stack([x, y])).volume) / 1e6  # 2-D hull volume = area
    except (QhullError, ValueError):  # collinear / degenerate
        return float("nan")


def coverage_stats(info: pd.DataFrame, *, zones: object = None) -> pd.Series:
    """Spatial coverage of a station network — density and dispersion.

    Reports nearest-neighbour spacing and station density. The density denominator is the
    convex hull of the stations by default, or — far more accurate for free-floating / hybrid
    systems — the **real service area** if you pass the operator's geofencing ``zones``
    (a GeoDataFrame from :func:`~gbfs_toolkit.to_canonical_geofencing`; needs the ``[geo]``
    extra). Also reports the **Clark–Evans index** (observed mean NN distance ÷ the value
    expected under spatial randomness: ``<1`` clustered, ``≈1`` random, ``>1`` dispersed).

    Returns
    -------
    pandas.Series
        ``n_stations``, ``mean_nearest_neighbor_m``, ``median_nearest_neighbor_m``,
        ``hull_area_km2`` *or* ``service_area_km2``, ``stations_per_km2``, ``clark_evans_index``.
    """
    lat, lon = _num(info, "lat").to_numpy(), _num(info, "lon").to_numpy()
    finite = np.isfinite(lat) & np.isfinite(lon)
    lat, lon = lat[finite], lon[finite]
    out: dict[str, float] = {"n_stations": int(lat.size)}
    if lat.size == 0:
        return pd.Series(out)

    if lat.size >= 2:
        from gbfs_toolkit.geo import GeoKDTree

        dist, _ = GeoKDTree(lat, lon).query(lat, lon, k=2)
        nn = np.asarray(dist)[:, 1]
        out["mean_nearest_neighbor_m"] = round(float(nn.mean()), 1)
        out["median_nearest_neighbor_m"] = round(float(np.median(nn)), 1)

    area_km2: float | None = None
    if zones is not None:
        from gbfs_toolkit.geofencing import zone_area_km2

        area_km2 = float(zone_area_km2(zones).sum())
        out["service_area_km2"] = round(area_km2, 3)
    elif lat.size >= 3:
        area_km2 = _hull_area_km2(lat, lon)
        out["hull_area_km2"] = round(area_km2, 3)

    if area_km2 and area_km2 > 0 and np.isfinite(area_km2):
        out["stations_per_km2"] = round(lat.size / area_km2, 3)
        if "mean_nearest_neighbor_m" in out:
            density_m2 = lat.size / (area_km2 * 1e6)
            expected_nn = 1.0 / (2.0 * np.sqrt(density_m2))
            out["clark_evans_index"] = round(out["mean_nearest_neighbor_m"] / expected_nn, 3)
    return pd.Series(out)


def availability_stats(panel: pd.DataFrame, *, time_col: str = "fetched_at") -> pd.DataFrame:
    """Per-station longitudinal statistics from an availability panel.

    Complements :func:`~gbfs_toolkit.diurnal_profiles` (which yields the curves) with
    comparable scalars per station: central tendency, time spent empty/full, volatility, and
    the diurnal amplitude / peak hour of occupancy.

    Parameters
    ----------
    panel : pandas.DataFrame
        A panel from :func:`~gbfs_toolkit.build_availability_panel` (MultiIndexed) or a flat
        frame with ``system_id, station_id, num_bikes_available, num_docks_available`` and a
        time column. Hour-of-day uses ``time_col`` **as stored** — pass a panel built with
        ``target_tz`` for local-time peaks.

    Returns
    -------
    pandas.DataFrame
        Indexed by ``(system_id, station_id)``: ``n_obs``, ``mean_bikes``, ``median_bikes``,
        ``occupancy_mean``, ``pct_time_empty``, ``pct_time_full``, ``volatility``,
        ``diurnal_amplitude``, ``peak_hour``.
    """
    df = panel.reset_index() if isinstance(panel.index, pd.MultiIndex) else panel.copy()
    bikes, docks = _num(df, "num_bikes_available"), _num(df, "num_docks_available")
    denom = bikes + docks
    work = pd.DataFrame(
        {
            "system_id": df["system_id"],
            "station_id": df["station_id"],
            "bikes": bikes,
            "occ": (bikes / denom).where(denom > 0),
            "empty": bikes <= 0,
            "full": docks <= 0,
            "hour": pd.to_datetime(df[time_col]).dt.hour,
        }
    )
    g = work.groupby(["system_id", "station_id"], sort=False)
    res = pd.DataFrame(
        {
            "n_obs": g.size(),
            "mean_bikes": g["bikes"].mean(),
            "median_bikes": g["bikes"].median(),
            "occupancy_mean": g["occ"].mean(),
            "pct_time_empty": g["empty"].mean(),
            "pct_time_full": g["full"].mean(),
            "volatility": g["bikes"].std(),
        }
    )

    hourly = work.groupby(["system_id", "station_id", "hour"])["occ"].mean().dropna()
    if len(hourly):
        by_station = hourly.groupby(level=[0, 1])
        res["diurnal_amplitude"] = by_station.max() - by_station.min()
        res["peak_hour"] = by_station.idxmax().map(lambda t: t[2])
    else:
        res["diurnal_amplitude"] = np.nan
        res["peak_hour"] = np.nan
    return res

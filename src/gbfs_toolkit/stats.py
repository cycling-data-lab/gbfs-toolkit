"""Descriptive statistics: readable summaries of canonical frames.

The plumbing (ingest / audit / panel) turns feeds into tidy data; this module turns tidy
data into the numbers a researcher actually reports. Strictly **descriptive**: no OD/trip
inference, no prediction (those belong in dedicated research code). All functions are pure
and pandas-only.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from gbfs_toolkit.analysis import STATION_STATES, station_state
from gbfs_toolkit.models import require_columns


def _num(df: pd.DataFrame, col: str) -> pd.Series:
    """Numeric view of a column (NaN where absent/unparseable)."""
    if col not in df.columns:
        return pd.Series(np.nan, index=df.index, dtype="float64")
    return pd.to_numeric(df[col], errors="coerce")


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
    """How concentrated is capacity across stations? An equity / coverage lens.

    Reports the **Gini coefficient** and **Theil T index** of ``value_col`` and the share held
    by the top decile of stations (a system can claim wide coverage yet stash most bikes in a
    few central hubs). Deliberately *outside* the published A1–A7 audit taxonomy; these are
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
    """Global **Moran's I**: spatial autocorrelation of ``value_col`` across stations.

    Answers "are similar values geographically clustered?" (e.g. are empty/low-occupancy
    stations grouped together, an equity / accessibility signal). Uses row-standardised
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
    """**Ripley's K / L**: multi-scale clustering of station locations.

    For each radius, ``K(r)`` is proportional to the mean number of other stations within
    ``r``; ``L(r) = sqrt(K(r)/π) − r`` linearises it: ``L(r) > 0`` ⇒ clustering at scale ``r``,
    ``< 0`` ⇒ dispersion. Density uses the convex hull by default, or ``area_km2`` (e.g. the
    geofencing service area) if given.

    .. warning::
       **No edge correction.** This estimator has no isotropic/translation boundary correction,
       so it is biased downward at radii approaching the study-area size and is unreliable for
       irregular real-world boundaries (coastlines, rivers, city limits). Use it for *relative*
       comparison at small radii, and prefer the boundary-robust Clark–Evans index in
       :func:`coverage_stats` for an overall dispersion verdict.

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
    """Spatial coverage of a station network: density and dispersion.

    Reports nearest-neighbour spacing and station density. The density denominator is the
    convex hull of the stations by default, or (far more accurate for free-floating / hybrid
    systems) the **real service area** if you pass the operator's geofencing ``zones``
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
        time column. Hour-of-day uses ``time_col`` **as stored**; pass a panel built with
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


def _gini(values: np.ndarray) -> float:
    """Gini coefficient of non-negative values (0 = equal, 1 = maximally concentrated)."""
    v = np.sort(np.asarray(values, dtype="float64"))
    v = v[np.isfinite(v)]
    n = v.size
    if n == 0 or v.sum() == 0:
        return float("nan")
    cum = np.cumsum(v)
    return float((n + 1 - 2 * np.sum(cum) / cum[-1]) / n)


def spatial_entropy(
    vehicle_panel: pd.DataFrame, *, grid_size_m: float = 200.0, time_col: str = "fetched_at"
) -> pd.DataFrame:
    """Shannon entropy of the free-floating fleet's spatial distribution over time.

    A free-floating system tends to collapse entropically (vehicles pile into city centres or
    topographic low points). Tracking the Shannon entropy of the per-snapshot distribution over a
    fixed metric grid objectifies that concentration without depending on administrative
    boundaries: high entropy is an even spread, low entropy is concentration.

    For each snapshot, vehicles are binned into ``grid_size_m`` cells (equirectangular projection)
    and :math:`H = -\\sum_i p_i \\ln p_i` is computed over the occupied cells, where :math:`p_i` is
    the share of the fleet in cell :math:`i`. ``evenness`` normalises by :math:`\\ln(\\text{cells})`
    so it is comparable across snapshots with different footprints.

    Parameters
    ----------
    vehicle_panel : pandas.DataFrame
        A history of canonical ``VehicleStatus`` rows; needs ``lat, lon`` and ``time_col``.
    grid_size_m : float, default 200.0
        Grid cell size in metres.
    time_col : str, default "fetched_at"
        Snapshot timestamp to group by.

    Returns
    -------
    pandas.DataFrame
        One row per snapshot: ``<time_col>, n_vehicles, n_cells, shannon_entropy, evenness``.
    """
    df = (
        vehicle_panel.reset_index()
        if isinstance(vehicle_panel.index, pd.MultiIndex)
        else vehicle_panel.copy()
    )
    require_columns(df, ["lat", "lon", time_col], what="spatial_entropy")
    lat = pd.to_numeric(df["lat"], errors="coerce")
    lon = pd.to_numeric(df["lon"], errors="coerce")
    finite = lat.notna() & lon.notna()
    df = df.loc[finite].copy()
    if df.empty:
        return pd.DataFrame(
            columns=[time_col, "n_vehicles", "n_cells", "shannon_entropy", "evenness"]
        )
    lat_f, lon_f = lat[finite].to_numpy(), lon[finite].to_numpy()
    mean_lat = np.deg2rad(np.mean(lat_f))
    x = _EARTH_RADIUS_M * np.deg2rad(lon_f) * np.cos(mean_lat)
    y = _EARTH_RADIUS_M * np.deg2rad(lat_f)
    df["_cell"] = list(
        zip(
            np.floor(x / grid_size_m).astype("int64"),
            np.floor(y / grid_size_m).astype("int64"),
            strict=True,
        )
    )

    rows = []
    for t, g in df.groupby(time_col, sort=True):
        counts = g.groupby("_cell").size().to_numpy()
        p = counts / counts.sum()
        h = float(-(p * np.log(p)).sum())
        n_cells = int(len(counts))
        rows.append(
            {
                time_col: t,
                "n_vehicles": int(len(g)),
                "n_cells": n_cells,
                "shannon_entropy": h,
                "evenness": h / np.log(n_cells) if n_cells > 1 else 0.0,
            }
        )
    return pd.DataFrame(rows)


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
    """
    df = panel.reset_index() if isinstance(panel.index, pd.MultiIndex) else panel.copy()
    require_columns(df, [time_col, target_col], what="dynamic_gini_index")
    vals = pd.to_numeric(df[target_col], errors="coerce")
    rows = []
    for t, idx in df.groupby(time_col, sort=True).groups.items():
        v = vals.loc[idx].dropna().to_numpy()
        rows.append({time_col: t, "gini": _gini(v), "n_stations": int(v.size)})
    return pd.DataFrame(rows)


def spatial_center_of_mass(
    panel: pd.DataFrame,
    *,
    freq: str = "1h",
    weight_col: str = "num_bikes_available",
    time_col: str = "fetched_at",
) -> pd.DataFrame:
    """Fleet centre of gravity over time: the weighted-mean station coordinate per period.

    Summarises the whole network's spatial dynamics as one moving point. In hilly or monocentric
    cities the centre of mass drifts downhill or toward the centre over the day, which is the
    signature of the pendular migration that forces heavy evening rebalancing.

    Parameters
    ----------
    panel : pandas.DataFrame
        A panel joined with station coordinates: needs ``lat, lon, time_col`` and ``weight_col``.
    freq : str, default "1h"
        Aggregation bin (a pandas offset alias).
    weight_col : str, default "num_bikes_available"
        Weight for the mean (e.g. available bikes).

    Returns
    -------
    pandas.DataFrame
        ``period, center_lat, center_lon, total_weight``.
    """
    df = panel.reset_index() if isinstance(panel.index, pd.MultiIndex) else panel.copy()
    require_columns(df, ["lat", "lon", time_col, weight_col], what="spatial_center_of_mass")
    w = pd.to_numeric(df[weight_col], errors="coerce").fillna(0.0).to_numpy()
    lat = pd.to_numeric(df["lat"], errors="coerce").to_numpy()
    lon = pd.to_numeric(df["lon"], errors="coerce").to_numpy()
    period = pd.to_datetime(df[time_col]).dt.floor(freq)
    work = pd.DataFrame({"period": period.to_numpy(), "_wlat": w * lat, "_wlon": w * lon, "_w": w})
    agg = work.groupby("period").sum()
    out = pd.DataFrame(
        {
            "period": agg.index,
            "center_lat": agg["_wlat"] / agg["_w"].where(agg["_w"] > 0),
            "center_lon": agg["_wlon"] / agg["_w"].where(agg["_w"] > 0),
            "total_weight": agg["_w"].to_numpy(),
        }
    ).reset_index(drop=True)
    return out


def diurnal_summary_stats(
    panel: pd.DataFrame, *, value_col: str = "num_bikes_available", time_col: str = "fetched_at"
) -> pd.DataFrame:
    """Hour-of-day summary of a quantity: mean, median and robust P5/P95 bands.

    The aggregation behind the classic diurnal usage curve with its uncertainty ribbon. Provided
    once so studies do not re-derive ``groupby(hour).agg(...)`` with ad-hoc, outlier-sensitive
    percentiles. Convert the panel to local time first for local-hour semantics.

    Returns
    -------
    pandas.DataFrame
        ``hour`` (0 to 23) with ``mean, median, p05, p95, n``.
    """
    df = panel.reset_index() if isinstance(panel.index, pd.MultiIndex) else panel.copy()
    require_columns(df, [value_col, time_col], what="diurnal_summary_stats")
    work = pd.DataFrame(
        {
            "hour": pd.to_datetime(df[time_col]).dt.hour.to_numpy(),
            "_v": pd.to_numeric(df[value_col], errors="coerce").to_numpy(),
        }
    )
    g = work.groupby("hour")["_v"]
    out = g.agg(["mean", "median", "size"]).rename(columns={"size": "n"})
    out["p05"] = g.quantile(0.05)
    out["p95"] = g.quantile(0.95)
    return out.reset_index()[["hour", "mean", "median", "p05", "p95", "n"]]


def local_morans_i(
    info: pd.DataFrame,
    value_col: str,
    *,
    k: int = 8,
    permutations: int = 999,
    seed: int = 0,
) -> pd.DataFrame:
    """Local Moran's I (LISA): per-station spatial-autocorrelation hotspots and cold spots.

    Where :func:`morans_i` returns one global number ("is there a pattern?"), LISA localises it:
    each station gets a local statistic, a permutation pseudo p-value, and a cluster label, so a
    study can map *where* the low-availability cold spots or high-turnover hot spots are.

    With deviations :math:`z_i = x_i - \\bar{x}` and row-standardised k-nearest-neighbour weights,
    the local statistic is :math:`I_i = (z_i / m_2)\\sum_j w_{ij} z_j`, where
    :math:`m_2 = \\frac{1}{n}\\sum_i z_i^2`. Significance is a conditional-permutation pseudo
    p-value; each station is labelled ``HH`` (high value, high neighbours), ``LL``, ``HL`` or
    ``LH`` (spatial outliers) when significant, else ``ns``. Requires scipy (``[geo]`` weights).

    Parameters
    ----------
    info : pandas.DataFrame
        Canonical station inventory with ``lat, lon`` and ``value_col``.
    value_col : str
        The variable to test (for example occupancy or turnover).
    k : int, default 8
        Number of nearest neighbours for the spatial weights.
    permutations : int, default 999
        Permutations for the pseudo p-value.
    seed : int, default 0
        Seed for the permutation draw (reproducible).

    Returns
    -------
    pandas.DataFrame
        Aligned to ``info``: ``local_i, z_score, p_value, cluster_type`` (and ``station_id`` when
        present). Non-finite inputs yield ``NaN`` / ``"ns"``.

    References
    ----------
    Anselin, L. (1995). Local Indicators of Spatial Association (LISA). *Geographical Analysis*,
    27(2), 93-115.
    """
    from gbfs_toolkit.geo import GeoKDTree

    require_columns(info, ["lat", "lon", value_col], what="local_morans_i")
    base = info.reset_index(drop=True)
    lat = pd.to_numeric(base["lat"], errors="coerce").to_numpy()
    lon = pd.to_numeric(base["lon"], errors="coerce").to_numpy()
    x = _num(base, value_col).to_numpy()
    finite = np.isfinite(lat) & np.isfinite(lon) & np.isfinite(x)

    out = pd.DataFrame(index=base.index)
    if "station_id" in base.columns:
        out["station_id"] = base["station_id"]
    out["local_i"] = np.nan
    out["z_score"] = np.nan
    out["p_value"] = np.nan
    out["cluster_type"] = "ns"

    n = int(finite.sum())
    kk = min(k, n - 1)
    if n < 3 or kk < 1:
        return out

    pos = np.where(finite)[0]
    lat_f, lon_f, xf = lat[pos], lon[pos], x[pos]
    _, idx = GeoKDTree(lat_f, lon_f).query(lat_f, lon_f, k=kk + 1)
    neighbours = np.asarray(idx)[:, 1 : kk + 1]  # drop self

    z = xf - xf.mean()
    m2 = float((z**2).mean())
    if m2 == 0:
        return out
    lag = z[neighbours].mean(axis=1)
    local_i = (z / m2) * lag

    rng = np.random.default_rng(seed)
    abs_obs = np.abs(local_i)
    ge = np.zeros(n)
    s1 = np.zeros(n)
    s2 = np.zeros(n)
    for _ in range(permutations):
        pz = rng.permutation(z)
        i_perm = (z / m2) * pz[neighbours].mean(axis=1)
        ge += np.abs(i_perm) >= abs_obs
        s1 += i_perm
        s2 += i_perm**2
    p = (ge + 1.0) / (permutations + 1.0)
    mean_perm = s1 / permutations
    std_perm = np.sqrt(np.maximum(s2 / permutations - mean_perm**2, 1e-12))
    zscore = (local_i - mean_perm) / std_perm

    sig = p <= 0.05
    hi_z, hi_lag = z > 0, lag > 0
    ctype = np.full(n, "ns", dtype=object)
    ctype[sig & hi_z & hi_lag] = "HH"
    ctype[sig & ~hi_z & ~hi_lag] = "LL"
    ctype[sig & hi_z & ~hi_lag] = "HL"
    ctype[sig & ~hi_z & hi_lag] = "LH"

    out.loc[pos, "local_i"] = local_i
    out.loc[pos, "z_score"] = zscore
    out.loc[pos, "p_value"] = p
    out.loc[pos, "cluster_type"] = ctype
    return out


def diurnal_bimodality(
    panel: pd.DataFrame, *, value_col: str = "num_bikes_available", time_col: str = "fetched_at"
) -> pd.DataFrame:
    """Sarle's bimodality coefficient of each station's diurnal profile.

    Clustering yields unsupervised typologies; this yields a single, continuous, thresholded
    scalar that separates commuter stations (a bimodal morning/evening profile) from recreational
    or residential ones (unimodal). For the mean hourly profile with sample skewness :math:`g_1`
    and excess kurtosis :math:`g_2`,

    .. math::
        \\mathrm{BC} = \\frac{g_1^2 + 1}{g_2 + \\frac{3(n-1)^2}{(n-2)(n-3)}},

    and ``BC > 5/9 ≈ 0.555`` suggests bimodality.

    Returns
    -------
    pandas.DataFrame
        Per station: ``bimodality_coefficient`` (float), ``is_bimodal`` (boolean) and
        ``peak_hour`` (hour of the busiest bin).

    References
    ----------
    Pfister et al. (2013); Sarle's bimodality coefficient. Bikeshare diurnal context: Vogel et al.
    (2011).
    """
    from scipy.stats import kurtosis, skew

    df = panel.reset_index() if isinstance(panel.index, pd.MultiIndex) else panel.copy()
    require_columns(df, ["station_id", value_col, time_col], what="diurnal_bimodality")
    work = pd.DataFrame(
        {
            "station_id": df["station_id"].to_numpy(),
            "hour": pd.to_datetime(df[time_col]).dt.hour.to_numpy(),
            "_v": pd.to_numeric(df[value_col], errors="coerce").to_numpy(),
        }
    )
    profiles = work.groupby(["station_id", "hour"])["_v"].mean().unstack("hour")
    rows = []
    for sid, profile in profiles.iterrows():
        a = profile.dropna().to_numpy()
        n = a.size
        if n < 4 or np.allclose(a, a[0]):
            bc = np.nan
        else:
            g1 = float(skew(a, bias=False))
            g2 = float(kurtosis(a, fisher=True, bias=False))
            denom = g2 + 3.0 * (n - 1) ** 2 / ((n - 2) * (n - 3))
            bc = (g1**2 + 1.0) / denom if denom != 0 else np.nan
        peak_hour = int(profile.idxmax()) if profile.notna().any() else -1
        rows.append(
            {
                "station_id": sid,
                "bimodality_coefficient": bc,
                "is_bimodal": pd.NA if np.isnan(bc) else bool(bc > 5 / 9),
                "peak_hour": peak_hour,
            }
        )
    out = pd.DataFrame(rows)
    out["is_bimodal"] = out["is_bimodal"].astype("boolean")
    return out

"""Spatial statistics: autocorrelation, clustering, entropy, centre of mass, accessibility.

Standard descriptive spatial algorithms (Moran's I global and local, Ripley's K/L, Clark–Evans,
Shannon entropy, fleet centre of mass, 2SFCA accessibility) over canonical station and panel
frames. Deterministic, numpy/scipy only. Exposed on the ``.gbfs`` accessor.

This is a sibling of :mod:`gbfs_toolkit.analytics.*`; it imports only ``core`` and
``spatial.geometry`` and must not import any ``analytics`` module (to keep the layering acyclic).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from gbfs_toolkit.core.models import require_columns
from gbfs_toolkit.core.utils import EARTH_RADIUS_M, num
from gbfs_toolkit.spatial.geometry import GeoKDTree, haversine_m


def _knn_weights(lat: np.ndarray, lon: np.ndarray, k: int):
    """Row-standardised binary k-nearest-neighbour spatial weights (sparse)."""
    from scipy.sparse import csr_matrix, diags

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
    lat, lon = num(info, "lat").to_numpy(), num(info, "lon").to_numpy()
    finite = np.isfinite(lat) & np.isfinite(lon)
    lat, lon = lat[finite], lon[finite]
    radii = np.asarray(radii, dtype="float64")
    n = lat.size
    if n < 2:
        return pd.DataFrame({"radius_m": radii, "k": np.nan, "l": np.nan})

    area_m2 = (area_km2 * 1e6) if area_km2 is not None else _hull_area_km2(lat, lon) * 1e6

    tree = GeoKDTree(lat, lon)
    ks = []
    for r in radii:
        hits = tree.query_radius(lat, lon, radius_m=float(r))
        pairs = sum(len(h) - 1 for h in hits)  # exclude self
        ks.append(area_m2 * pairs / (n * (n - 1)) if np.isfinite(area_m2) else np.nan)
    k_arr = np.asarray(ks)
    l_arr = np.sqrt(k_arr / np.pi) - radii
    return pd.DataFrame({"radius_m": radii, "k": k_arr, "l": l_arr})


def _hull_area_km2(lat: np.ndarray, lon: np.ndarray) -> float:
    """Convex-hull area (km²) of points, via an equal-area-ish local projection."""
    from scipy.spatial import ConvexHull, QhullError

    lat_r, lon_r = np.radians(lat), np.radians(lon)
    mean_lat = float(np.mean(lat_r))
    x = EARTH_RADIUS_M * lon_r * np.cos(mean_lat)
    y = EARTH_RADIUS_M * lat_r
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
    lat, lon = num(info, "lat").to_numpy(), num(info, "lon").to_numpy()
    finite = np.isfinite(lat) & np.isfinite(lon)
    lat, lon = lat[finite], lon[finite]
    out: dict[str, float] = {"n_stations": int(lat.size)}
    if lat.size == 0:
        return pd.Series(out)

    if lat.size >= 2:
        dist, _ = GeoKDTree(lat, lon).query(lat, lon, k=2)
        nn = np.asarray(dist)[:, 1]
        out["mean_nearest_neighbor_m"] = round(float(nn.mean()), 1)
        out["median_nearest_neighbor_m"] = round(float(np.median(nn)), 1)

    area_km2: float | None = None
    if zones is not None:
        from gbfs_toolkit.spatial.geofencing import zone_area_km2

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
    x = EARTH_RADIUS_M * np.deg2rad(lon_f) * np.cos(mean_lat)
    y = EARTH_RADIUS_M * np.deg2rad(lat_f)
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


def fdr_adjust(pvalues, *, method: str = "bh") -> np.ndarray:
    """Multiple-testing correction of a vector of p-values (Benjamini-Hochberg).

    LISA and per-station tests run one hypothesis per station; at thousands of
    stations the uncorrected count of "significant" hot/cold spots is dominated by
    false positives. This returns FDR-adjusted p-values (NaNs preserved), so a
    study can threshold on a controlled false-discovery rate instead of a raw
    per-test alpha.

    Parameters
    ----------
    pvalues : array-like
        Raw p-values (may contain NaN for untested units).
    method : {"bh", "by"}, default "bh"
        Benjamini-Hochberg (independent/positively-dependent) or
        Benjamini-Yekutieli (arbitrary dependence).

    References
    ----------
    Benjamini, Y. & Hochberg, Y. (1995). Controlling the false discovery rate.
    *JRSS B*, 57(1), 289-300.
    """
    from scipy.stats import false_discovery_control

    p = np.asarray(pvalues, dtype="float64")
    out = np.full(p.shape, np.nan)
    finite = np.isfinite(p)
    if finite.any():
        out[finite] = false_discovery_control(p[finite], method=method)
    return out


def local_morans_i(
    info: pd.DataFrame,
    value_col: str,
    *,
    k: int = 8,
    permutations: int = 999,
    seed: int = 0,
    fdr: bool = False,
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
    require_columns(info, ["lat", "lon", value_col], what="local_morans_i")
    base = info.reset_index(drop=True)
    lat = pd.to_numeric(base["lat"], errors="coerce").to_numpy()
    lon = pd.to_numeric(base["lon"], errors="coerce").to_numpy()
    x = pd.to_numeric(base[value_col], errors="coerce").to_numpy()
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
    # Variance with ddof=1, matching the PySAL/esda Moran_Local normalisation so the
    # reported local_i is directly comparable to that reference implementation.
    m2 = float((z**2).sum() / (z.size - 1)) if z.size > 1 else 0.0
    if m2 == 0:
        return out
    lag = z[neighbours].mean(axis=1)
    local_i = (z / m2) * lag

    if permutations < 1:
        # No inference requested: report the statistic only, no pseudo p-value or z-score.
        out.loc[pos, "local_i"] = local_i
        return out

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

    # Benjamini-Hochberg correction across stations before labelling, so the cluster
    # set controls the false-discovery rate rather than a raw per-station alpha.
    p_sig = fdr_adjust(p) if fdr else p
    sig = p_sig <= 0.05
    hi_z, hi_lag = z > 0, lag > 0
    ctype = np.full(n, "ns", dtype=object)
    ctype[sig & hi_z & hi_lag] = "HH"
    ctype[sig & ~hi_z & ~hi_lag] = "LL"
    ctype[sig & hi_z & ~hi_lag] = "HL"
    ctype[sig & ~hi_z & hi_lag] = "LH"

    out.loc[pos, "local_i"] = local_i
    out.loc[pos, "z_score"] = zscore
    out.loc[pos, "p_value"] = p
    if fdr:
        out["fdr_p"] = np.nan
        out.loc[pos, "fdr_p"] = p_sig
    out.loc[pos, "cluster_type"] = ctype
    return out


def _decay_weights(d: np.ndarray, d_max: float, decay: str) -> np.ndarray:
    """Distance-decay weights for a catchment of radius ``d_max``."""
    if decay == "none":
        return np.ones_like(d, dtype="float64")
    if decay == "linear":
        return np.clip(1.0 - d / d_max, 0.0, None)
    if decay == "gaussian":
        sigma = d_max / 3.0  # the catchment edge sits at ~3 sigma
        return np.exp(-0.5 * (d / sigma) ** 2)
    if decay == "exponential":
        # Gravity-style exponential decay; ~5% weight remains at the catchment edge.
        return np.exp(-3.0 * d / d_max)
    raise ValueError(
        f"decay must be 'gaussian', 'exponential', 'linear' or 'none', got {decay!r}"
    )


def _point_latlon(frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Latitude / longitude arrays from lat/lon columns or a GeoDataFrame geometry."""
    if "lat" in frame.columns and "lon" in frame.columns:
        return (
            pd.to_numeric(frame["lat"], errors="coerce").to_numpy(),
            pd.to_numeric(frame["lon"], errors="coerce").to_numpy(),
        )
    if hasattr(frame, "geometry"):
        geom = frame.geometry
        return geom.y.to_numpy(dtype="float64"), geom.x.to_numpy(dtype="float64")
    raise ValueError("demand needs 'lat'/'lon' columns or a GeoDataFrame point geometry")


def two_step_fca(
    info: pd.DataFrame,
    demand: pd.DataFrame,
    *,
    max_distance_m: float = 800.0,
    decay: str = "gaussian",
    supply_col: str = "capacity",
    demand_col: str = "population",
) -> pd.Series:
    """Two-step floating catchment area (2SFCA) accessibility, a spatial-equity measure.

    Concentration measures (Gini, Theil) capture inequality *inside* the network; 2SFCA captures
    equity of access *to* the network from where people are, the metric health geographers use to
    find mobility deserts. Step 1 computes a supply-to-demand ratio at each station (capacity over
    the distance-weighted population in its catchment); step 2 sums those ratios, distance-weighted,
    over the stations reachable from each demand location.

    Straight-line (great-circle) proximity only; no routing. Bring your own demand layer (no
    network calls).

    Parameters
    ----------
    info : pandas.DataFrame
        Canonical station inventory with ``lat, lon`` and ``supply_col``.
    demand : pandas.DataFrame or geopandas.GeoDataFrame
        Demand locations with ``demand_col`` and either ``lat``/``lon`` columns or a point geometry.
    max_distance_m : float, default 800.0
        Catchment radius in metres.
    decay : {"gaussian", "linear", "none"}, default "gaussian"
        Distance-decay weighting within the catchment.
    supply_col, demand_col : str
        Columns holding station capacity and location demand (e.g. population).

    Returns
    -------
    pandas.Series
        Accessibility score per demand location, aligned to ``demand.index``
        (``name="accessibility_2sfca"``). Higher is better served.

    References
    ----------
    Luo and Wang (2003); Radke and Mu (2000). Applied to bike-share equity by e.g. Qian et al. (2020).
    """
    require_columns(info, ["lat", "lon", supply_col], what="two_step_fca")
    require_columns(demand, [demand_col], what="two_step_fca")
    slat = pd.to_numeric(info["lat"], errors="coerce").to_numpy()
    slon = pd.to_numeric(info["lon"], errors="coerce").to_numpy()
    supply = pd.to_numeric(info[supply_col], errors="coerce").fillna(0.0).to_numpy()
    dlat, dlon = _point_latlon(demand)
    dem = pd.to_numeric(demand[demand_col], errors="coerce").fillna(0.0).to_numpy()

    # Step 1: supply-to-demand ratio R_j at each station.
    r_j = np.zeros(len(supply), dtype="float64")
    demand_tree = GeoKDTree(dlat, dlon)
    for j, idx in enumerate(demand_tree.query_radius(slat, slon, radius_m=max_distance_m)):
        if idx.size == 0:
            continue
        d = haversine_m(slat[j], slon[j], dlat[idx], dlon[idx])
        weighted_demand = float((dem[idx] * _decay_weights(d, max_distance_m, decay)).sum())
        if weighted_demand > 0:
            r_j[j] = supply[j] / weighted_demand

    # Step 2: sum the reachable ratios at each demand location.
    access = np.zeros(len(dem), dtype="float64")
    supply_tree = GeoKDTree(slat, slon)
    for i, idx in enumerate(supply_tree.query_radius(dlat, dlon, radius_m=max_distance_m)):
        if idx.size == 0:
            continue
        d = haversine_m(dlat[i], dlon[i], slat[idx], slon[idx])
        access[i] = float((r_j[idx] * _decay_weights(d, max_distance_m, decay)).sum())

    return pd.Series(access, index=demand.index, name="accessibility_2sfca")

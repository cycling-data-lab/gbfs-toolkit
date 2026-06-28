"""The empirical compiler: read a real GBFS feed, fingerprint it, and fit the simulator to it.

Frugal geometry (``cKDTree``, never the dense N^2 matrix), capacity-based land use, a three-metric
thermodynamic footprint (turnover, lag-1h ACF1, stockout rate), and a grid search that recovers the
``SimConfig`` whose simulated footprint matches the real one. The result is a calibrated digital twin.
"""

from __future__ import annotations

from itertools import product

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from gbfs_toolkit.sim.flows import SimConfig, simulate_city_flows

EARTH_KM = 6371.0


def extract_geometry(df_info: pd.DataFrame, radius_km: float = 6.0):
    """Lat/lon -> Cartesian XYZ -> ``cKDTree``; return coords, capacity, ids and the sparse pairs."""
    info = df_info.dropna(subset=["lat", "lon", "capacity"]).reset_index(drop=True)
    phi, lam = np.radians(info["lat"].to_numpy()), np.radians(info["lon"].to_numpy())
    xyz = EARTH_KM * np.column_stack(
        [np.cos(phi) * np.cos(lam), np.cos(phi) * np.sin(lam), np.sin(phi)]
    )
    pairs = cKDTree(xyz).query_pairs(r=radius_km, output_type="ndarray")
    return (
        info["lat"].to_numpy(),
        info["lon"].to_numpy(),
        info["capacity"].to_numpy(dtype=float),
        info["station_id"].to_numpy(),
        pairs,
    )


def assign_roles(capacity: np.ndarray) -> np.ndarray:
    """Heuristic land use from the capacity distribution (indices match ``flows._ROLES``)."""
    q75, q95 = np.percentile(capacity, [75, 95])
    role = np.zeros(capacity.size, dtype=int)  # 0 = residential (<= 75th)
    role[capacity >= q75] = 1  # 1 = employment (75th-95th)
    role[capacity >= q95] = 2  # 2 = hub_heavy (top 5%)
    return role


def compute_footprint(df_panel: pd.DataFrame) -> np.ndarray:
    """``[turnover/day, median ACF1(lag 1h), stockout_rate]`` from a GBFS station_status history."""
    p = df_panel.copy()
    p["fetched_at"] = pd.to_datetime(p["fetched_at"], utc=True)
    cap = (
        p.assign(c=p["num_bikes_available"] + p["num_docks_available"])
        .groupby("station_id", observed=True)["c"]
        .max()
    )
    wide = (
        p.pivot_table(
            index="fetched_at", columns="station_id", values="num_bikes_available", observed=True
        )
        .sort_index()
        .resample("1h")
        .last()
    )
    arr = wide.to_numpy(dtype=float)
    capv = cap.reindex(wide.columns).to_numpy(dtype=float)

    trips = np.nansum(np.abs(np.diff(arr, axis=0))) / 2.0
    days = max((wide.index[-1] - wide.index[0]).total_seconds() / 86400, 1e-9)
    turnover = trips / max(capv.sum(), 1.0) / days

    acfs = []
    for j in range(arr.shape[1]):
        col = arr[:, j][~np.isnan(arr[:, j])]
        if col.size > 2 and col.std() > 1e-6:
            acfs.append(np.corrcoef(col[:-1], col[1:])[0, 1])
    acf1 = float(np.median(acfs)) if acfs else 0.0

    stockout = float(np.nanmean((arr <= 1e-9) | (arr >= capv[None, :] - 1e-9)))
    return np.array([turnover, acf1, stockout])


def calibrate_city(
    df_info: pd.DataFrame,
    target_footprint: np.ndarray,
    *,
    days: int = 3,
    weights: tuple[float, float, float] = (1.0, 2.0, 1.0),
    seed: int = 0,
) -> dict:
    """Grid-search ``SimConfig`` hyperparameters so the simulated footprint matches the real one."""
    lat, lon, cap, _ids, _pairs = extract_geometry(df_info)
    role = assign_roles(cap)
    w = np.asarray(weights, dtype=float)
    scale = np.maximum(np.abs(target_footprint), 1e-6)

    results = []
    for beta, base, tr in product([1.0, 2.0, 3.0], [0.1, 0.4, 0.8], [6.0, 10.0, 14.0]):
        cfg = SimConfig(
            days=days,
            freq="1h",
            seed=seed,
            topography=False,
            ghost_rate=0.0,
            weather_events=0,
            scraper_cell_nan=0.0,
            scraper_station_outages=0,
            beta_km=beta,
            base_demand=base,
            trip_rate=tr,
            inject_lat=lat,
            inject_lon=lon,
            inject_capacity=cap,
            inject_role=role,
        )
        _, status = simulate_city_flows(cfg)
        fp = compute_footprint(status)
        mse = float(np.sum(w * ((fp - target_footprint) / scale) ** 2))
        results.append((mse, (beta, base, tr), fp, cfg))

    results.sort(key=lambda r: r[0])
    mse, params, fp, cfg = results[0]
    return {
        "best_params": dict(zip(["beta_km", "base_demand", "trip_rate"], params, strict=False)),
        "best_config": cfg,
        "best_footprint": fp,
        "mse": mse,
        "target": target_footprint,
    }

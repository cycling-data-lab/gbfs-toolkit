"""Static semantic audit of a docked GBFS system — the A1–A7 taxonomy.

Ported from the published ``gbfs-audit-catalogue`` pipeline (Fossé & Pallares),
adapted to the toolkit's canonical :data:`~gbfs_toolkit.models.STATION_INFO_COLUMNS`
schema. Operates purely on an in-memory frame (no I/O), so it can audit feeds you
fetched yourself or any third-party station inventory.

Row-level flags (this station): A1, A3, A4.
System-level flags (all rows of a flagged system): A2, A5, A6, A7.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from gbfs_toolkit.models import (
    A2_MIN_STATIONS,
    A4_MIN_STATIONS,
    A4_MIN_THRESHOLD_M,
    A4_SIGMA,
    A5_BBOX_MAX_KM2,
    A6_MIN_STATIONS,
    A6_RATE_THRESHOLD,
    A7_MIN_STATIONS,
    A7_RATE_THRESHOLD,
    AUDIT_FLAGS,
    RULES,
    require_columns,
)

_EARTH_RADIUS_M = 6_371_000.0
_REQUIRED = ["system_id", "station_id", "station_type", "capacity", "lat", "lon"]


def _project_meters(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """Equirectangular projection to local metres around the dataset mean."""
    lat_r = np.deg2rad(np.asarray(lat, dtype="float64"))
    lon_r = np.deg2rad(np.asarray(lon, dtype="float64"))
    if lat_r.size == 0:
        return np.empty((0, 2), dtype="float64")
    mean_lat = float(np.nanmean(lat_r))
    x = _EARTH_RADIUS_M * lon_r * np.cos(mean_lat)
    y = _EARTH_RADIUS_M * lat_r
    return np.column_stack([x, y])


def _flag_a2(df: pd.DataFrame) -> pd.Series:
    """A2 — placeholder capacity: constant non-zero capacity across a docked system."""
    docked = df[df["station_type"] == "docked_bike"]
    caps = (
        docked.dropna(subset=["capacity"])
        .groupby("system_id")["capacity"]
        .agg(["nunique", "median", "size"])
    )
    flagged = set(
        caps.index[
            (caps["nunique"] == 1) & (caps["median"] > 0) & (caps["size"] >= A2_MIN_STATIONS)
        ]
    )
    return df["system_id"].isin(flagged)


def _flag_a4(df: pd.DataFrame, projected: np.ndarray) -> np.ndarray:
    """A4 — geospatial outliers via a robust 3-sigma rule on nearest-neighbour distance."""
    from scipy.spatial import cKDTree

    n = len(df)
    flag = np.zeros(n, dtype=bool)
    if n == 0:
        return flag
    sys_codes, _ = pd.factorize(df["system_id"].to_numpy())
    for code in np.unique(sys_codes):
        idx = np.where(sys_codes == code)[0]
        if len(idx) < A4_MIN_STATIONS:
            continue
        pts = projected[idx]
        finite = np.isfinite(pts).all(axis=1)
        if finite.sum() < A4_MIN_STATIONS:
            continue
        idx_f, pts = idx[finite], pts[finite]
        tree = cKDTree(pts)
        dists, _ = tree.query(pts, k=2)  # self + nearest
        nn = dists[:, 1]
        nn_med = float(np.median(nn))
        mad = float(np.median(np.abs(nn - nn_med)))
        sigma = 1.4826 * mad
        if sigma > 0.0:
            threshold = max(nn_med + A4_SIGMA * sigma, A4_MIN_THRESHOLD_M)
        else:
            threshold = max(10.0 * nn_med, A4_MIN_THRESHOLD_M)
        flag[idx_f[nn > threshold]] = True
    return flag


def _flag_a5(df: pd.DataFrame, projected: np.ndarray) -> np.ndarray:
    """A5 — out-of-perimeter: system bounding box larger than the threshold area."""
    n = len(df)
    flag = np.zeros(n, dtype=bool)
    if n == 0:
        return flag
    sys_codes, _ = pd.factorize(df["system_id"].to_numpy())
    for code in np.unique(sys_codes):
        idx = np.where(sys_codes == code)[0]
        pts = projected[idx]
        pts = pts[np.isfinite(pts).all(axis=1)]
        if len(pts) < 2:
            continue
        area_km2 = ((pts[:, 0].max() - pts[:, 0].min()) * (pts[:, 1].max() - pts[:, 1].min())) / 1e6
        if area_km2 > A5_BBOX_MAX_KM2:
            flag[idx] = True
    return flag


def _flag_a6(df: pd.DataFrame) -> pd.Series:
    """A6 — at least 1% of a system's docked stations declare capacity = 0."""
    is_zero = (df["capacity"].fillna(-1) == 0) & (df["station_type"] == "docked_bike")
    rate = is_zero.groupby(df["system_id"]).mean()
    size = df.groupby("system_id").size()
    flagged = set(rate.index[(rate >= A6_RATE_THRESHOLD) & (size >= A6_MIN_STATIONS)])
    return df["system_id"].isin(flagged)


def _flag_a7(df: pd.DataFrame) -> pd.Series:
    """A7 — at least 50% of a system's stations declare capacity = NaN."""
    rate = df["capacity"].isna().groupby(df["system_id"]).mean()
    size = df.groupby("system_id").size()
    flagged = set(rate.index[(rate >= A7_RATE_THRESHOLD) & (size >= A7_MIN_STATIONS)])
    return df["system_id"].isin(flagged)


def audit_static(stations: pd.DataFrame) -> pd.DataFrame:
    """Run the A1–A7 semantic audit on a canonical station-information frame.

    Parameters
    ----------
    stations : pandas.DataFrame
        Canonical station inventory; requires
        ``system_id, station_id, station_type, capacity, lat, lon``.

    Returns
    -------
    pandas.DataFrame
        One row per input station with boolean columns ``A1 … A7``, a
        ``flagged`` column (any rule fired) and a human-readable ``reason``
        (comma-separated rule names).
    """
    require_columns(stations, _REQUIRED, what="audit_static")
    df = stations.reset_index(drop=True)
    projected = _project_meters(
        df["lat"].to_numpy(dtype="float64"), df["lon"].to_numpy(dtype="float64")
    )

    out = pd.DataFrame({"system_id": df["system_id"], "station_id": df["station_id"]})
    out["A1"] = (df["station_type"] == "carsharing").to_numpy()
    out["A2"] = _flag_a2(df).to_numpy()
    out["A3"] = (df["station_type"] == "free_floating").to_numpy()
    out["A4"] = _flag_a4(df, projected)
    out["A5"] = _flag_a5(df, projected)
    out["A6"] = _flag_a6(df).to_numpy()
    out["A7"] = _flag_a7(df).to_numpy()

    flags = out[list(AUDIT_FLAGS)].to_numpy()
    out["flagged"] = flags.any(axis=1)
    out["reason"] = [
        ", ".join(RULES[f]["name"] for f, fired in zip(AUDIT_FLAGS, row, strict=True) if fired)
        for row in flags
    ]
    return out

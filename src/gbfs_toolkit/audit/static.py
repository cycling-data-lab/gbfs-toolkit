"""Static semantic audit of a docked GBFS system: the A1–A7 taxonomy.

Ported from the published ``gbfs-audit-catalogue`` pipeline (Fossé & Pallares),
adapted to the toolkit's canonical :data:`~gbfs_toolkit.core.models.STATION_INFO_COLUMNS`
schema. Operates purely on an in-memory frame (no I/O), so it can audit feeds you
fetched yourself or any third-party station inventory.

Row-level flags (this station): A1, A3, A4.
System-level flags (all rows of a flagged system): A2, A5, A6, A7.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from gbfs_toolkit.core.models import (
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
from gbfs_toolkit.core.utils import EARTH_RADIUS_M, project_meters

_REQUIRED = ["system_id", "station_id", "station_type", "capacity", "lat", "lon"]


def _docked_mask(df: pd.DataFrame) -> pd.Series:
    """Physical docked stations only; excludes free-floating *and* virtual anchors.

    Capacity-distribution rules (A2/A6/A7) must ignore virtual/free-float "stations",
    whose capacity is routinely 0/null by design; otherwise a mostly free-floating
    system (Lime/Tier/Bird) trips every capacity flag as a false positive.
    """
    mask = df["station_type"] == "docked_bike"
    if "is_virtual_station" in df.columns:
        mask &= ~df["is_virtual_station"].fillna(False).astype(bool)
    return mask


def _lon_span_deg(lon: np.ndarray) -> float:
    """Smallest longitudinal arc (degrees) covering all points; anti-meridian safe.

    Plain ``max(lon) - min(lon)`` reports ~360° for a cluster straddling ±180°. The
    true extent is ``360 - (largest gap between adjacent longitudes)``.
    """
    lon = np.sort(np.mod(np.asarray(lon, dtype="float64"), 360.0))
    if lon.size < 2:
        return 0.0
    gaps = np.diff(lon)
    wrap_gap = 360.0 - (lon[-1] - lon[0])
    largest_gap = max(float(gaps.max()), wrap_gap)
    return 360.0 - largest_gap


def _flag_a2(df: pd.DataFrame) -> pd.Series:
    """A2, placeholder capacity: constant non-zero capacity across a docked system."""
    docked = df[_docked_mask(df)]
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


def _flag_a4(df: pd.DataFrame, projected: np.ndarray, a4_sigma: float = A4_SIGMA) -> np.ndarray:
    """A4: geospatial outliers via a robust ``a4_sigma``-sigma rule on nearest-neighbour
    distance (default :data:`~gbfs_toolkit.core.models.A4_SIGMA`)."""
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
            threshold = max(nn_med + a4_sigma * sigma, A4_MIN_THRESHOLD_M)
        else:
            threshold = max(10.0 * nn_med, A4_MIN_THRESHOLD_M)
        flag[idx_f[nn > threshold]] = True
    return flag


def _flag_a5(df: pd.DataFrame) -> np.ndarray:
    """A5, out-of-perimeter: system bounding box larger than the threshold area.

    The longitudinal extent uses the smallest covering arc (:func:`_lon_span_deg`), so a
    system straddling the ±180° antimeridian is not falsely reported as Earth-spanning.
    """
    n = len(df)
    flag = np.zeros(n, dtype=bool)
    if n == 0:
        return flag
    lat = df["lat"].to_numpy(dtype="float64")
    lon = df["lon"].to_numpy(dtype="float64")
    sys_codes, _ = pd.factorize(df["system_id"].to_numpy())
    for code in np.unique(sys_codes):
        idx = np.where(sys_codes == code)[0]
        finite = np.isfinite(lat[idx]) & np.isfinite(lon[idx])
        if finite.sum() < 2:
            continue
        slat, slon = lat[idx][finite], lon[idx][finite]
        height_m = EARTH_RADIUS_M * np.deg2rad(slat.max() - slat.min())
        mean_lat_r = np.deg2rad(float(np.mean(slat)))
        width_m = EARTH_RADIUS_M * np.deg2rad(_lon_span_deg(slon)) * np.cos(mean_lat_r)
        if (width_m * height_m) / 1e6 > A5_BBOX_MAX_KM2:
            flag[idx] = True
    return flag


def _flag_a6(df: pd.DataFrame) -> pd.Series:
    """A6: at least 1% of a system's docked stations declare capacity = 0."""
    docked = df[_docked_mask(df)]
    if docked.empty:
        return pd.Series(False, index=df.index)
    is_zero = docked["capacity"].fillna(-1) == 0
    rate = is_zero.groupby(docked["system_id"]).mean()
    size = docked.groupby("system_id").size()
    flagged = set(rate.index[(rate >= A6_RATE_THRESHOLD) & (size >= A6_MIN_STATIONS)])
    return df["system_id"].isin(flagged)


def _flag_a7(df: pd.DataFrame, scope: str = "docked") -> pd.Series:
    """A7: at least 50% of a system's stations declare capacity = NaN.

    Parameters
    ----------
    scope : {"docked", "all"}, default "docked"
        ``"docked"`` restricts the rate to physical docked stations, so free-floating
        and virtual anchors (which legitimately carry null capacity) do not flag every
        dockless system spuriously. ``"all"`` evaluates the rate over every station in
        the system, reproducing the original ``gbfs-audit-catalogue`` definition, under
        which a fully free-floating system with null capacities does trip A7.
    """
    if scope not in ("docked", "all"):
        raise ValueError(f"a7_scope must be 'docked' or 'all', got {scope!r}")
    sub = df if scope == "all" else df[_docked_mask(df)]
    if sub.empty:
        return pd.Series(False, index=df.index)
    rate = sub["capacity"].isna().groupby(sub["system_id"]).mean()
    size = sub.groupby("system_id").size()
    flagged = set(rate.index[(rate >= A7_RATE_THRESHOLD) & (size >= A7_MIN_STATIONS)])
    return df["system_id"].isin(flagged)


def audit_static(
    stations: pd.DataFrame, *, a7_scope: str = "docked", a4_sigma: float = A4_SIGMA
) -> pd.DataFrame:
    """Run the A1–A7 semantic audit on a canonical station-information frame.

    Parameters
    ----------
    stations : pandas.DataFrame
        Canonical station inventory; requires
        ``system_id, station_id, station_type, capacity, lat, lon``.
    a7_scope : {"docked", "all"}, default "docked"
        Scope of the A7 null-capacity rule. ``"docked"`` (default) counts only physical
        docked stations, so dockless systems are not flagged spuriously. ``"all"`` counts
        every station, reproducing the original ``gbfs-audit-catalogue`` verdicts.
    a4_sigma : float, default :data:`~gbfs_toolkit.core.models.A4_SIGMA`
        Multiplier of the robust (MAD-rescaled) scale in the A4 nearest-neighbour outlier
        rule. Exposed for sensitivity analysis; the published default is ``3.0``.

    Returns
    -------
    pandas.DataFrame
        One row per input station with boolean columns ``A1 … A7``, a
        ``flagged`` column (any rule fired) and a human-readable ``reason``
        (comma-separated rule names).
    """
    require_columns(stations, _REQUIRED, what="audit_static")
    df = stations.reset_index(drop=True)
    projected = project_meters(
        df["lat"].to_numpy(dtype="float64"), df["lon"].to_numpy(dtype="float64")
    )

    out = pd.DataFrame({"system_id": df["system_id"], "station_id": df["station_id"]})
    out["A1"] = (df["station_type"] == "carsharing").to_numpy()
    out["A2"] = _flag_a2(df).to_numpy()
    out["A3"] = (df["station_type"] == "free_floating").to_numpy()
    out["A4"] = _flag_a4(df, projected, a4_sigma=a4_sigma)
    out["A5"] = _flag_a5(df)
    out["A6"] = _flag_a6(df).to_numpy()
    out["A7"] = _flag_a7(df, scope=a7_scope).to_numpy()

    flags = out[list(AUDIT_FLAGS)].to_numpy()
    out["flagged"] = flags.any(axis=1)
    out["reason"] = [
        ", ".join(RULES[f]["name"] for f, fired in zip(AUDIT_FLAGS, row, strict=True) if fired)
        for row in flags
    ]
    return out

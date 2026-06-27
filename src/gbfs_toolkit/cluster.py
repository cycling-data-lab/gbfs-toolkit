"""Station clustering & zoning — geographic, topological, and behavioural.

Three lenses on "which stations belong together":

* :func:`cluster_spatial` — physical proximity (HDBSCAN/DBSCAN on projected metres).
* :func:`cluster_spectral` — network/topological groups (geographic affinity → graph
  Laplacian eigenvectors → k-means, via scikit-learn). For the research-grade spectral
  *profile* of a network (R²_spec bound, localization), use the sibling ``spectral-mobility``.
* :func:`cluster_diurnal_profiles` — **behavioural typologies** from a longitudinal panel
  (e.g. "morning commuter origin", "nightlife hub") — the payoff of the longitudinal layer.

Requires the optional ``[cluster]`` extra (``scikit-learn``).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

_EARTH_RADIUS_M = 6_371_000.0


def _require_sklearn():
    try:
        import sklearn  # noqa: F401
    except ImportError as e:  # pragma: no cover
        raise ImportError(
            "Clustering requires scikit-learn. Install with `pip install gbfs-toolkit[cluster]`."
        ) from e


def _project_xy(lat: Any, lon: Any) -> np.ndarray:
    """Equirectangular projection to local metres around the dataset mean (clustering-grade)."""
    lat_r = np.radians(np.asarray(lat, dtype="float64"))
    lon_r = np.radians(np.asarray(lon, dtype="float64"))
    mean_lat = float(np.nanmean(lat_r)) if lat_r.size else 0.0
    return np.column_stack([_EARTH_RADIUS_M * lon_r * np.cos(mean_lat), _EARTH_RADIUS_M * lat_r])


def cluster_spatial(
    info: pd.DataFrame,
    *,
    method: str = "hdbscan",
    min_cluster_size: int = 3,
    eps_m: float = 300.0,
) -> pd.DataFrame:
    """Group stations into spatial zones by physical proximity.

    Returns ``info`` with a ``cluster`` column (``-1`` = noise/unclustered).

    Parameters
    ----------
    method : {"hdbscan", "dbscan"}
        HDBSCAN auto-selects density scales; DBSCAN uses a fixed ``eps_m`` radius.
    min_cluster_size : int
        Minimum stations to form a zone.
    eps_m : float
        Neighbourhood radius in metres (DBSCAN only).
    """
    _require_sklearn()
    out = info.reset_index(drop=True).copy()
    if out.empty:
        out["cluster"] = pd.Series(dtype="int64")
        return out
    xy = _project_xy(out["lat"], out["lon"])  # Euclidean-safe metres, not raw lat/lon
    if method == "hdbscan":
        from sklearn.cluster import HDBSCAN

        labels = HDBSCAN(min_cluster_size=min_cluster_size).fit_predict(xy)
    elif method == "dbscan":
        from sklearn.cluster import DBSCAN

        labels = DBSCAN(eps=eps_m, min_samples=min_cluster_size).fit_predict(xy)
    else:
        raise ValueError(f"unknown method {method!r}; use 'hdbscan' or 'dbscan'")
    out["cluster"] = labels.astype("int64")
    return out


def cluster_spectral(info: pd.DataFrame, *, k: int, n_neighbors: int = 10) -> pd.DataFrame:
    """Topological clustering: geographic kNN affinity → Laplacian spectrum → k-means.

    Returns ``info`` with a ``spectral_cluster`` column. Groups by network significance
    rather than raw distance (e.g. a bridge or a corridor).
    """
    _require_sklearn()
    out = info.reset_index(drop=True).copy()
    n = len(out)
    if n == 0:
        out["spectral_cluster"] = pd.Series(dtype="int64")
        return out
    from sklearn.cluster import SpectralClustering

    xy = _project_xy(out["lat"], out["lon"])
    sc = SpectralClustering(
        n_clusters=min(k, n),
        affinity="nearest_neighbors",
        n_neighbors=min(n_neighbors, max(1, n - 1)),
        assign_labels="kmeans",
        random_state=0,
    )
    out["spectral_cluster"] = sc.fit_predict(xy).astype("int64")
    return out


def _occupancy(df: pd.DataFrame) -> pd.Series:
    """Fraction of capacity filled (0–1), falling back to bikes/(bikes+docks)."""
    bikes = pd.to_numeric(df["num_bikes_available"], errors="coerce")
    occ = pd.Series(np.nan, index=df.index, dtype="float64")
    if "capacity" in df:
        cap = pd.to_numeric(df["capacity"], errors="coerce")
        occ = bikes.where(cap <= 0, bikes / cap)
        occ = occ.where(cap > 0)  # invalid where capacity unusable
    if "num_docks_available" in df:
        docks = pd.to_numeric(df["num_docks_available"], errors="coerce")
        total = bikes + docks
        alt = bikes.where(total <= 0, bikes / total)
        occ = occ.fillna(alt)
    return occ.clip(0.0, 1.0)


def cluster_diurnal_profiles(
    panel: pd.DataFrame,
    *,
    n_clusters: int = 4,
    min_obs: int = 12,
    time_col: str = "fetched_at",
    random_state: int = 0,
) -> pd.DataFrame:
    """Cluster stations by their **daily rhythm** (the crown jewel of the longitudinal layer).

    Builds each station's 24-hour occupancy profile (mean fraction-of-capacity by hour of
    day — robust to irregular sampling and missing ticks), then k-means clusters the
    profiles into typologies (commuter origin, recreational, always-full, …).

    Parameters
    ----------
    panel : pandas.DataFrame
        A panel from :func:`~gbfs_toolkit.build_availability_panel` (MultiIndexed) or a flat
        frame with ``system_id, station_id, num_bikes_available`` and a timestamp column.
        Pass a *local-time* panel (``GBFSFeed.to_local_time``) if you care about local
        diurnal phase; otherwise hours are UTC.
    n_clusters : int, default 4
    min_obs : int, default 12
        Minimum observations for a station to be profiled (others are dropped).
    time_col : str, default "fetched_at"
        Timestamp column used for the hour-of-day.

    Returns
    -------
    pandas.DataFrame
        One row per profiled station: ``system_id, station_id, cluster, n_obs`` and the
        24 profile columns ``h00 … h23``.
    """
    _require_sklearn()
    from sklearn.cluster import KMeans

    df = panel.reset_index() if isinstance(panel.index, pd.MultiIndex) else panel.copy()
    df = df.copy()
    df["_occ"] = _occupancy(df)
    df["_hour"] = pd.to_datetime(df[time_col], utc=True).dt.hour

    n_obs = df.groupby(["system_id", "station_id"])["_occ"].count()
    prof = df.pivot_table(
        index=["system_id", "station_id"], columns="_hour", values="_occ"
    ).reindex(columns=range(24))
    # fill an unobserved hour by the station's own mean (don't model data outages)
    prof = prof.apply(lambda row: row.fillna(row.mean()), axis=1).dropna(how="any")
    keep = n_obs[n_obs >= min_obs].index
    prof = prof.loc[prof.index.intersection(keep)]
    if prof.empty:
        return pd.DataFrame(
            columns=[
                "system_id",
                "station_id",
                "cluster",
                "n_obs",
                *[f"h{h:02d}" for h in range(24)],
            ]
        )

    k = min(n_clusters, len(prof))
    labels = KMeans(n_clusters=k, n_init=10, random_state=random_state).fit_predict(prof.to_numpy())

    out = prof.copy()
    out.columns = [f"h{h:02d}" for h in range(24)]
    out["cluster"] = labels.astype("int64")
    out = out.reset_index()
    out["n_obs"] = out.set_index(["system_id", "station_id"]).index.map(n_obs).to_numpy()
    front = ["system_id", "station_id", "cluster", "n_obs"]
    return out[front + [c for c in out.columns if c not in front]]

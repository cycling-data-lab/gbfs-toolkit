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


def diurnal_profiles(
    panel: pd.DataFrame,
    *,
    time_col: str = "fetched_at",
    split_weekday: bool = False,
    min_obs: int = 12,
) -> tuple[pd.DataFrame, pd.Series]:
    """Build each station's mean occupancy profile by hour of day.

    Robust to irregular sampling (aggregates by hour), fills an unobserved hour with the
    station's own mean. With ``split_weekday`` the profile is 48-dim (weekday ``wd*`` +
    weekend ``we*``), capturing commute-vs-leisure rhythms separately.

    Returns ``(profiles, n_obs)`` — ``profiles`` indexed by ``(system_id, station_id)``
    with hour columns, and the per-station observation count.
    """
    df = panel.reset_index() if isinstance(panel.index, pd.MultiIndex) else panel.copy()
    df = df.copy()
    df["_occ"] = _occupancy(df)
    ts = pd.to_datetime(df[time_col], utc=True)
    df["_hour"] = ts.dt.hour
    n_obs = df.groupby(["system_id", "station_id"])["_occ"].count()

    if split_weekday:
        df["_seg"] = np.where(ts.dt.dayofweek < 5, "wd", "we")
        df["_col"] = df["_seg"] + df["_hour"].map(lambda h: f"{h:02d}")
        order = [f"{s}{h:02d}" for s in ("wd", "we") for h in range(24)]
    else:
        df["_col"] = df["_hour"].map(lambda h: f"h{h:02d}")
        order = [f"h{h:02d}" for h in range(24)]

    prof = df.pivot_table(index=["system_id", "station_id"], columns="_col", values="_occ")
    prof = prof.reindex(columns=order)
    prof = prof.apply(lambda row: row.fillna(row.mean()), axis=1).dropna(how="any")
    keep = n_obs[n_obs >= min_obs].index
    prof = prof.loc[prof.index.intersection(keep)]
    return prof, n_obs


def _select_k(x: np.ndarray, k_range: tuple[int, int], random_state: int) -> int:
    """Pick the number of clusters maximising the silhouette score over ``k_range``."""
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score

    lo, hi = k_range
    hi = min(hi, len(x) - 1)
    if hi < lo or len(x) <= 2:
        return max(2, min(lo, len(x)))
    best_k, best_s = lo, -1.0
    for k in range(lo, hi + 1):
        labels = KMeans(n_clusters=k, n_init=10, random_state=random_state).fit_predict(x)
        if len(set(labels)) < 2:
            continue
        s = silhouette_score(x, labels)
        if s > best_s:
            best_k, best_s = k, s
    return best_k


def cluster_diurnal_profiles(
    panel: pd.DataFrame,
    *,
    n_clusters: int | str = "auto",
    method: str = "kmeans",
    normalize: str = "none",
    split_weekday: bool = False,
    min_obs: int = 12,
    k_range: tuple[int, int] = (2, 8),
    time_col: str = "fetched_at",
    random_state: int = 0,
) -> pd.DataFrame:
    """Cluster stations by their **daily rhythm** (the crown jewel of the longitudinal layer).

    Builds each station's occupancy-by-hour profile, then clusters into typologies
    (commuter origin, recreational, always-full, …).

    Parameters
    ----------
    panel : pandas.DataFrame
        A panel from :func:`~gbfs_toolkit.build_availability_panel` (or a flat frame with
        ``system_id, station_id, num_bikes_available`` + a timestamp). Pass a *local-time*
        panel (``GBFSFeed.to_local_time``) for local diurnal phase; else hours are UTC.
    n_clusters : int or "auto", default "auto"
        Fixed k, or ``"auto"`` to pick the best k by silhouette over ``k_range``.
    method : {"kmeans", "gmm", "dtw"}, default "kmeans"
        ``gmm`` = soft Gaussian-mixture (adds a ``cluster_confidence`` column);
        ``dtw`` = shape-aware time-series k-means (needs ``tslearn``).
    normalize : {"none", "zscore"}, default "none"
        ``zscore`` clusters by rhythm *shape* (per-station standardised), ignoring the
        average occupancy level — usually what you want for "commuter vs leisure".
    split_weekday : bool, default False
        Profile weekday and weekend separately (48-dim).
    min_obs : int, default 12
        Minimum observations for a station to be profiled.

    Returns
    -------
    pandas.DataFrame
        ``system_id, station_id, cluster, n_obs`` (+ ``cluster_confidence`` for gmm) and the
        profile columns.
    """
    _require_sklearn()

    prof, n_obs = diurnal_profiles(
        panel, time_col=time_col, split_weekday=split_weekday, min_obs=min_obs
    )
    cols = list(prof.columns)
    if prof.empty:
        return pd.DataFrame(columns=["system_id", "station_id", "cluster", "n_obs", *cols])

    x = prof.to_numpy(dtype="float64")
    if normalize == "zscore":  # cluster by shape, not level
        mu = x.mean(axis=1, keepdims=True)
        sd = x.std(axis=1, keepdims=True)
        x = (x - mu) / np.where(sd > 0, sd, 1.0)

    k = (
        _select_k(x, k_range, random_state)
        if n_clusters == "auto"
        else min(int(n_clusters), len(x))
    )

    confidence = None
    if method == "kmeans":
        from sklearn.cluster import KMeans

        labels = KMeans(n_clusters=k, n_init=10, random_state=random_state).fit_predict(x)
    elif method == "gmm":
        from sklearn.mixture import GaussianMixture

        gmm = GaussianMixture(n_components=k, random_state=random_state).fit(x)
        labels = gmm.predict(x)
        confidence = gmm.predict_proba(x).max(axis=1)
    elif method == "dtw":
        try:
            from tslearn.clustering import TimeSeriesKMeans
        except ImportError as e:  # pragma: no cover
            raise ImportError("method='dtw' requires tslearn (`pip install tslearn`).") from e
        labels = TimeSeriesKMeans(
            n_clusters=k, metric="dtw", random_state=random_state
        ).fit_predict(x.reshape(x.shape[0], x.shape[1], 1))
    else:
        raise ValueError(f"unknown method {method!r}; use 'kmeans', 'gmm' or 'dtw'")

    out = prof.copy()
    out["cluster"] = np.asarray(labels).astype("int64")
    if confidence is not None:
        out["cluster_confidence"] = confidence
    out = out.reset_index()
    out["n_obs"] = out.set_index(["system_id", "station_id"]).index.map(n_obs).to_numpy()
    front = ["system_id", "station_id", "cluster", "n_obs"]
    if confidence is not None:
        front.append("cluster_confidence")
    return out[front + [c for c in out.columns if c not in front]]


#: Behavioural typology names returned by :func:`label_diurnal_typology`.
DIURNAL_TYPOLOGIES = (
    "mostly_empty",
    "mostly_full",
    "morning_origin",
    "morning_destination",
    "evening_origin",
    "recreational",
    "stable",
)


def label_diurnal_typology(profiles: pd.DataFrame, *, amplitude: float = 0.15) -> pd.Series:
    """Assign a **human-readable behavioural type** to each station from its 24-h profile.

    Interprets the occupancy curve (columns ``h00 … h23``) into named types — far more useful
    than integer cluster ids:

    * ``morning_origin`` — empties in the morning (commuters depart): a residential origin.
    * ``morning_destination`` — fills in the morning (commuters arrive): a job/transit hub.
    * ``evening_origin`` — empties in the evening.
    * ``recreational`` — midday/afternoon peak.
    * ``mostly_empty`` / ``mostly_full`` — chronically saturated either way.
    * ``stable`` — little diurnal variation.

    Parameters
    ----------
    profiles : pandas.DataFrame
        Output of :func:`cluster_diurnal_profiles` / :func:`diurnal_profiles` with ``h00..h23``.
    amplitude : float, default 0.15
        Minimum morning/evening swing (fraction of capacity) to call a directional type.

    Returns
    -------
    pandas.Series
        Categorical typology, aligned to ``profiles`` rows.
    """
    hours = [f"h{h:02d}" for h in range(24)]
    missing = [h for h in hours if h not in profiles.columns]
    if missing:
        raise KeyError(f"label_diurnal_typology needs 24-hour columns; missing {missing[:3]}…")
    p = profiles[hours].to_numpy(dtype="float64")
    night = p[:, list(range(0, 5))].mean(axis=1)
    morning = p[:, list(range(7, 11))].mean(axis=1)
    midday = p[:, list(range(11, 16))].mean(axis=1)
    evening = p[:, list(range(17, 21))].mean(axis=1)
    mean_occ = p.mean(axis=1)
    morning_delta = morning - night
    evening_delta = evening - midday

    out = np.full(p.shape[0], "stable", dtype=object)
    for i in range(p.shape[0]):
        if mean_occ[i] < 0.1:
            out[i] = "mostly_empty"
        elif mean_occ[i] > 0.9:
            out[i] = "mostly_full"
        elif morning_delta[i] <= -amplitude:
            out[i] = "morning_origin"
        elif morning_delta[i] >= amplitude:
            out[i] = "morning_destination"
        elif evening_delta[i] <= -amplitude:
            out[i] = "evening_origin"
        elif midday[i] - (night[i] + evening[i]) / 2 >= amplitude:
            out[i] = "recreational"
    return pd.Series(
        pd.Categorical(out, categories=list(DIURNAL_TYPOLOGIES)),
        index=profiles.index,
        name="typology",
    )

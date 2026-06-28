"""Package a simulated city as data: a canonical GBFS Parquet archive and an analysis-ready ML folder.

``generate_gbfs_parquet`` writes a compressed, downcast ``station_status`` panel that mimics a
multi-month GBFS scrape (the archive, for audit and ETL). ``export_ml_dataset`` writes the wide
matrices a spatio-temporal model trains on, with an explicit observation mask (the guard against
spatial-imputation leakage) and a strict temporal split.
"""

from __future__ import annotations

import json
import os

import numpy as np
import pandas as pd

from gbfs_toolkit.sim.flows import SimConfig, simulate_city_flows


def generate_gbfs_parquet(cfg: SimConfig, filepath: str) -> dict:
    """Run the simulation and export a compressed, canonical GBFS ``station_status`` Parquet.

    Ghost bikes are split into ``num_bikes_disabled`` (rentable count goes to
    ``num_bikes_available``); a scraper failure drops the snapshot (a real gap), not a null value.
    Counts are downcast to nullable ``Int16`` and ``station_id`` to ``category``.
    """
    info, status = simulate_city_flows(cfg)
    ghost = info.set_index("station_id")["ghost_bikes"]
    df = status.copy()
    g = df["station_id"].map(ghost).to_numpy()
    total = df["num_bikes_available"].to_numpy(
        dtype="float64"
    )  # physical (incl. ghost), may be NaN
    capv = info.set_index("station_id")["capacity"].reindex(df["station_id"]).to_numpy()
    df["num_bikes_available"] = total - g  # rentable
    df["num_bikes_disabled"] = g
    df["num_docks_available"] = capv - total
    df["fetched_at"] = pd.to_datetime(df["fetched_at"], utc=True)
    df = df[df["num_bikes_available"].notna()].copy()  # scraper failure = missing snapshot
    df["station_id"] = df["station_id"].astype("category")
    for col in ("num_bikes_available", "num_bikes_disabled", "num_docks_available"):
        df[col] = df[col].round().astype("Int16")
    keep = [
        "system_id",
        "station_id",
        "fetched_at",
        "num_bikes_available",
        "num_bikes_disabled",
        "num_docks_available",
        "is_renting",
        "is_returning",
        "is_installed",
        "last_reported",
        "gbfs_version",
    ]
    df[keep].to_parquet(filepath, engine="pyarrow", compression="snappy", index=False)
    info.to_parquet(filepath.replace(".parquet", "_meta.parquet"), index=False)
    return {"rows": len(df), "bytes": os.path.getsize(filepath)}


def export_ml_dataset(
    cfg: SimConfig,
    outdir: str,
    *,
    k_graph: int = 10,
    n_eigen: int = 64,
    train_frac: float = 0.66,
    val_frac: float = 0.17,
) -> dict:
    """Write the analysis-ready ML folder for one simulated city.

    Produces wide time-by-station matrices of absolute ``num_bikes_available`` (Int16, NaN at
    missing snapshots) and capacity, an explicit boolean observation mask, a ``graph_geometry.npz``
    (coords, kNN adjacency, Laplacian eigenbasis), and a ``splits.json`` with strict temporal
    train/val/test boundaries. Absolute counts, not a capacity ratio; no derived temporal features.
    """
    from gbfs_toolkit.spatial.graph import knn_adjacency, normalized_laplacian

    os.makedirs(outdir, exist_ok=True)
    info, _ = simulate_city_flows(cfg)
    long_path = f"{outdir}/station_status_long.parquet"
    generate_gbfs_parquet(cfg, long_path)
    long = pd.read_parquet(long_path)
    long["station_id"] = long["station_id"].astype(str)

    wide = long.pivot_table(
        index="fetched_at", columns="station_id", values="num_bikes_available", observed=True
    ).sort_index()
    stations = list(wide.columns)
    cap_vec = info.set_index("station_id")["capacity"].reindex(stations).to_numpy()
    cap_wide = pd.DataFrame(
        np.broadcast_to(cap_vec, wide.shape), index=wide.index, columns=stations
    )
    mask = wide.notna()

    wide.astype("Int16").to_parquet(f"{outdir}/bikes_available.parquet")
    cap_wide.astype("Int16").to_parquet(f"{outdir}/capacity.parquet")
    mask.to_parquet(f"{outdir}/observation_mask.parquet")

    idx = info.set_index("station_id").reindex(stations)
    lat, lon = idx["lat"].to_numpy(), idx["lon"].to_numpy()
    W = knn_adjacency(lat, lon, k=k_graph)
    evals, evecs = np.linalg.eigh(normalized_laplacian(W))
    np.savez_compressed(
        f"{outdir}/graph_geometry.npz",
        station_id=np.array(stations),
        lat=lat,
        lon=lon,
        altitude=idx["altitude"].to_numpy(),
        capacity=cap_vec,
        adjacency=W.astype(np.float32),
        eigenvalues=evals[:n_eigen].astype(np.float32),
        eigenvectors=evecs[:, :n_eigen].astype(np.float32),
    )

    n_t = len(wide.index)
    i_tr, i_va = int(n_t * train_frac), int(n_t * (train_frac + val_frac))
    splits = {
        "note": "strict temporal split; do not impute test NaNs from neighbours (spatial leakage)",
        "train": {"rows": [0, i_tr]},
        "val": {"rows": [i_tr, i_va]},
        "test": {"rows": [i_va, n_t]},
    }
    with open(f"{outdir}/splits.json", "w") as f:
        json.dump(splits, f, indent=2)
    return {"T": n_t, "N": len(stations), "observed_frac": float(mask.to_numpy().mean())}

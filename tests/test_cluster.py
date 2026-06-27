"""Tests for station clustering (spatial, spectral, diurnal). Requires scikit-learn."""

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("sklearn")

from gbfs_toolkit import cluster_diurnal_profiles, cluster_spatial, cluster_spectral  # noqa: E402


def _two_blobs(n=12, sep=0.05):
    rng = np.random.default_rng(0)
    a = rng.normal([48.85, 2.35], 1e-3, size=(n, 2))
    b = rng.normal([48.85 + sep, 2.35 + sep], 1e-3, size=(n, 2))
    pts = np.vstack([a, b])
    return pd.DataFrame(
        {
            "system_id": "velib",
            "station_id": [str(i) for i in range(len(pts))],
            "lat": pts[:, 0],
            "lon": pts[:, 1],
        }
    )


def test_cluster_spatial_two_zones():
    info = _two_blobs()
    out = cluster_spatial(info, method="hdbscan", min_cluster_size=4)
    assert "cluster" in out.columns
    # the two well-separated blobs → two non-noise clusters
    real = {c for c in out["cluster"] if c != -1}
    assert len(real) == 2


def test_cluster_spectral_labels():
    out = cluster_spectral(_two_blobs(), k=2, n_neighbors=5)
    assert out["spectral_cluster"].nunique() == 2


def _diurnal_panel():
    """Two stations with opposite daily rhythms, one day of hourly polls."""
    rows = []
    base = pd.Timestamp("2026-06-01T00:00:00Z")
    for h in range(24):
        t = base + pd.Timedelta(hours=h)
        # commuter origin: full at night, empty during the day
        commuter = 18 if (h < 6 or h >= 20) else 2
        # recreational: opposite
        recreation = 2 if (h < 6 or h >= 20) else 18
        for sid, bikes in (("A", commuter), ("B", recreation)):
            rows.append(
                {
                    "system_id": "velib",
                    "station_id": sid,
                    "num_bikes_available": bikes,
                    "num_docks_available": 20 - bikes,
                    "capacity": 20,
                    "fetched_at": t,
                }
            )
    return pd.DataFrame(rows)


def test_cluster_diurnal_profiles_separates_typologies():
    out = cluster_diurnal_profiles(_diurnal_panel(), n_clusters=2, min_obs=12)
    assert set(out["station_id"]) == {"A", "B"}
    assert {f"h{h:02d}" for h in range(24)} <= set(out.columns)
    # opposite rhythms → different clusters
    labels = dict(zip(out["station_id"], out["cluster"], strict=True))
    assert labels["A"] != labels["B"]
    # commuter station A is full at midnight, empty at noon
    a = out[out.station_id == "A"].iloc[0]
    assert a["h00"] > a["h12"]


def test_cluster_diurnal_drops_sparse_stations():
    panel = _diurnal_panel()
    sparse = pd.DataFrame(
        [
            {
                "system_id": "velib",
                "station_id": "Z",
                "num_bikes_available": 5,
                "num_docks_available": 15,
                "capacity": 20,
                "fetched_at": pd.Timestamp("2026-06-01T03:00:00Z"),
            }
        ]
    )
    out = cluster_diurnal_profiles(
        pd.concat([panel, sparse], ignore_index=True), n_clusters=2, min_obs=12
    )
    assert "Z" not in set(out["station_id"])  # only 1 obs < min_obs

"""Tests for the 1.4.0 advanced descriptive analytics."""

import numpy as np
import pandas as pd
import pytest

import gbfs_toolkit as gb


@pytest.fixture
def panel():
    times = pd.date_range("2026-06-01", periods=48, freq="1h", tz="UTC")
    coords = {
        "s1": (48.85, 2.35),
        "s2": (48.86, 2.36),
        "s3": (48.80, 2.30),
        "s4": (48.84, 2.34),
        "s5": (48.90, 2.40),
    }
    rng = np.random.default_rng(1)
    rows = []
    for sid, (la, lo) in coords.items():
        for t in times:
            b = int(rng.integers(0, 16))
            rows.append(
                {
                    "system_id": "sys",
                    "station_id": sid,
                    "fetched_at": t,
                    "last_reported": t,
                    "num_bikes_available": b,
                    "num_docks_available": 15 - b,
                    "lat": la,
                    "lon": lo,
                    "capacity": 15,
                }
            )
    return pd.DataFrame(rows).set_index(["system_id", "station_id", "fetched_at"]).sort_index()


@pytest.fixture
def info():
    rng = np.random.default_rng(2)
    coords = {
        "s1": (48.85, 2.35),
        "s2": (48.86, 2.36),
        "s3": (48.80, 2.30),
        "s4": (48.84, 2.34),
        "s5": (48.90, 2.40),
    }
    return pd.DataFrame(
        [
            {
                "system_id": "sys",
                "station_id": k,
                "lat": v[0],
                "lon": v[1],
                "occ": float(rng.random()),
            }
            for k, v in coords.items()
        ]
    )


def test_local_morans_i(info):
    out = gb.local_morans_i(info, "occ", k=2, permutations=99)
    assert len(out) == len(info)
    assert {"local_i", "z_score", "p_value", "cluster_type"} <= set(out.columns)
    assert out["cluster_type"].isin({"HH", "LL", "HL", "LH", "ns"}).all()
    assert out["p_value"].dropna().between(0, 1).all()


def test_local_morans_i_handles_degenerate():
    # fewer than 3 finite points: no statistic, but a well-formed frame
    df = pd.DataFrame({"lat": [48.85, np.nan], "lon": [2.35, 2.36], "occ": [1.0, 2.0]})
    out = gb.local_morans_i(df, "occ", k=2, permutations=10)
    assert len(out) == 2
    assert out["cluster_type"].eq("ns").all()


def test_diurnal_bimodality(panel):
    out = gb.diurnal_bimodality(panel)
    assert {"bimodality_coefficient", "is_bimodal", "peak_hour"} <= set(out.columns)
    assert out["peak_hour"].between(0, 23).all()


def test_availability_synchrony(panel):
    out = gb.availability_synchrony(panel, min_overlap=5)
    assert list(out.columns) == ["station_a", "station_b", "corr", "n_overlap"]
    assert out["corr"].between(-1, 1).all()
    # 5 stations -> at most 10 unique pairs
    assert len(out) <= 10
    thinned = gb.availability_synchrony(panel, min_overlap=5, threshold=0.99)
    assert len(thinned) <= len(out)


def test_outage_survival(panel):
    episodes = gb.stockout_episodes(panel)
    out = gb.outage_survival(episodes, by="kind")
    assert {"duration_minutes", "survival", "at_risk", "median_recovery"} <= set(out.columns)
    # survival is a non-increasing probability in [0, 1]
    assert out["survival"].between(0, 1).all()


def test_temporal_concentration(panel):
    out = gb.temporal_concentration(panel)
    g = out["temporal_gini"].dropna()
    assert ((g >= 0) & (g <= 1)).all()
    assert out["peak_share"].dropna().between(0, 1).all()


def test_advanced_accessor_methods(panel, info):
    assert isinstance(info.gbfs.local_morans_i("occ", permutations=10), pd.DataFrame)
    assert isinstance(panel.gbfs.diurnal_bimodality(), pd.DataFrame)
    assert isinstance(panel.gbfs.temporal_concentration(), pd.DataFrame)

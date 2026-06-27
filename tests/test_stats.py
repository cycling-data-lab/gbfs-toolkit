"""Tests for the descriptive-stats module."""

import numpy as np
import pandas as pd
import pytest

from gbfs_toolkit import (
    availability_stats,
    compare_systems,
    concentration_metrics,
    coverage_stats,
    lorenz_curve,
    morans_i,
    ripley_k,
    system_profile,
)


def _availability(rows):
    # rows: (station_id, bikes, docks, capacity, is_renting)
    return pd.DataFrame(
        rows,
        columns=[
            "station_id",
            "num_bikes_available",
            "num_docks_available",
            "capacity",
            "is_renting",
        ],
    ).astype(
        {"num_bikes_available": "Int64", "num_docks_available": "Int64", "is_renting": "boolean"}
    )


def test_system_profile_counts_and_rates():
    av = _availability(
        [
            ("a", 5, 5, 10, True),  # normal, 50% occ
            ("b", 0, 10, 10, True),  # empty
            ("c", 10, 0, 10, True),  # full
            ("d", 3, 7, 10, False),  # disabled (not renting/returning)
        ]
    )
    av["is_returning"] = pd.array([True, True, True, False], dtype="boolean")
    prof = system_profile(av)
    assert prof["n_stations"] == 4
    assert prof["total_capacity"] == 40
    assert prof["total_bikes_available"] == 18
    assert prof["pct_empty"] == 0.25
    assert prof["pct_full"] == 0.25
    assert prof["pct_disabled"] == 0.25
    assert 0.0 <= prof["mean_occupancy"] <= 1.0


def test_compare_systems_one_row_per_system():
    a = _availability([("a", 5, 5, 10, True)])
    b = _availability([("x", 1, 9, 10, True), ("y", 9, 1, 10, True)])
    table = compare_systems({"velib": a, "bixi": b})
    assert list(table.index) == ["velib", "bixi"]
    assert table.loc["bixi", "n_stations"] == 2
    assert "mean_occupancy" in table.columns


def test_concentration_gini_equal_vs_skewed():
    equal = pd.DataFrame({"capacity": [10, 10, 10, 10]})
    skewed = pd.DataFrame({"capacity": [1, 1, 1, 97]})
    g_equal = concentration_metrics(equal)["gini"]
    g_skewed = concentration_metrics(skewed)["gini"]
    assert g_equal == 0.0
    assert g_skewed > 0.6
    # top decile (≥1 station) of the skewed system holds almost everything
    assert concentration_metrics(skewed)["top_decile_share"] > 0.9
    # Theil agrees with Gini on ordering: 0 for equal, positive for skewed
    assert concentration_metrics(equal)["theil"] == 0.0
    assert concentration_metrics(skewed)["theil"] > 0.0


def test_lorenz_curve_monotone_origin_to_unit():
    info = pd.DataFrame({"capacity": [1, 2, 3, 4]})
    lc = lorenz_curve(info)
    assert lc.iloc[0]["cum_population_share"] == 0.0
    assert lc.iloc[0]["cum_value_share"] == 0.0
    assert lc.iloc[-1]["cum_population_share"] == pytest.approx(1.0)
    assert lc.iloc[-1]["cum_value_share"] == pytest.approx(1.0)
    # value share never exceeds population share (curve sits below the diagonal)
    assert (lc["cum_value_share"] <= lc["cum_population_share"] + 1e-9).all()


def test_morans_i_positive_for_spatial_gradient():
    # value = row index → smooth spatial gradient → strong positive autocorrelation
    rows = [
        (f"s{i}{j}", 48.85 + i * 0.01, 2.35 + j * 0.01, float(i))
        for i in range(5)
        for j in range(5)
    ]
    info = pd.DataFrame(rows, columns=["station_id", "lat", "lon", "occ"])
    res = morans_i(info, "occ", k=4)
    assert res["morans_i"] > 0.3
    assert res["morans_i"] > res["expected_i"]
    assert res["p_value"] < 0.05
    assert res["n"] == 25


def test_ripley_l_positive_for_clustered_points():
    # two tight 2-D blobs far apart → at a within-blob scale, points cluster → L(r) > 0
    a = [(48.850 + 0.0002 * i, 2.350 + 0.0002 * j) for i in range(3) for j in range(3)]
    b = [(48.900 + 0.0002 * i, 2.400 + 0.0002 * j) for i in range(3) for j in range(3)]
    info = pd.DataFrame(a + b, columns=["lat", "lon"])
    info["station_id"] = [f"s{i}" for i in range(len(info))]
    out = ripley_k(info, radii=[50, 200, 1000])
    assert list(out.columns) == ["radius_m", "k", "l"]
    assert np.isfinite(out["k"]).all()
    # at a small within-cluster scale, points are clustered → L > 0
    assert out.iloc[0]["l"] > 0


def test_coverage_stats_density_and_dispersion():
    # 9 stations on a ~grid near Paris → hull area > 0, density computed, CE index near 1
    lat0, lon0 = 48.85, 2.35
    rows = [(f"s{i}{j}", lat0 + i * 0.01, lon0 + j * 0.01) for i in range(3) for j in range(3)]
    info = pd.DataFrame(rows, columns=["station_id", "lat", "lon"])
    cov = coverage_stats(info)
    assert cov["n_stations"] == 9
    assert cov["hull_area_km2"] > 0
    assert cov["stations_per_km2"] > 0
    assert cov["mean_nearest_neighbor_m"] > 0
    assert "clark_evans_index" in cov


def test_coverage_stats_uses_service_area_when_zones_given():
    pytest.importorskip("geopandas")
    from gbfs_toolkit import to_canonical_geofencing

    info = pd.DataFrame({"station_id": ["a", "b"], "lat": [48.855, 48.856], "lon": [2.351, 2.352]})
    raw = {
        "data": {
            "geofencing_zones": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [
                                    [2.34, 48.85],
                                    [2.36, 48.85],
                                    [2.36, 48.86],
                                    [2.34, 48.86],
                                    [2.34, 48.85],
                                ]
                            ],
                        },
                        "properties": {"name": "z"},
                    }
                ],
            }
        }
    }
    zones = to_canonical_geofencing(raw, system_id="x")
    cov = coverage_stats(info, zones=zones)
    assert "service_area_km2" in cov and cov["service_area_km2"] > 0
    assert "hull_area_km2" not in cov  # zones take precedence


def test_availability_stats_per_station():
    t = pd.to_datetime(["2026-01-01T08:00:00Z", "2026-01-01T09:00:00Z", "2026-01-01T18:00:00Z"])
    panel = pd.DataFrame(
        {
            "system_id": "velib",
            "station_id": ["a", "a", "a"],
            "num_bikes_available": [10, 0, 5],
            "num_docks_available": [0, 10, 5],
            "fetched_at": t,
        }
    )
    stats = availability_stats(panel)
    row = stats.loc[("velib", "a")]
    assert row["n_obs"] == 3
    assert row["pct_time_empty"] == pytest.approx(1 / 3)
    assert row["pct_time_full"] == pytest.approx(1 / 3)
    assert 0.0 <= row["occupancy_mean"] <= 1.0
    assert not np.isnan(row["diurnal_amplitude"])

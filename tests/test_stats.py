"""Tests for the descriptive-stats module."""

import numpy as np
import pandas as pd
import pytest

from gbfs_toolkit import (
    availability_stats,
    compare_systems,
    concentration_metrics,
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

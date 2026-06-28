"""Regression tests for the v1.6.2 correctness fixes (from the professionalism audit)."""

from __future__ import annotations

import pandas as pd
import pytest

import gbfs_toolkit as gb
from gbfs_toolkit.core.utils import offset_minutes

# --- spatial_outage_redundancy ---------------------------------------------


def test_sor_unobserved_neighbour_is_not_counted_empty():
    # station a empty at t1; its only neighbour b has NO reading at t1 -> unknown,
    # so this must NOT be a systemic outage (the pre-fix bug returned 1.0).
    panel = pd.DataFrame(
        {
            "station_id": ["a", "b", "a"],
            "lat": [48.8500, 48.8501, 48.8500],
            "lon": [2.3500, 2.3501, 2.3500],
            "fetched_at": pd.to_datetime(
                ["2026-01-01T08:00Z", "2026-01-01T07:00Z", "2026-01-01T08:00Z"]
            ),
            "num_bikes_available": [0, 5, 0],
        }
    )
    out = gb.spatial_outage_redundancy(panel, radius_m=300).set_index("station_id")
    assert float(out.loc["a", "local_outage_ratio"]) == 1.0
    assert float(out.loc["a", "systemic_outage_ratio"]) == 0.0


def test_sor_duplicate_polls_are_deduplicated_not_summed():
    # two readings of 1 bike at the same instant must not sum to 2 ("not empty");
    # the station is genuinely occupied and n_obs counts the distinct timestamp once.
    panel = pd.DataFrame(
        {
            "station_id": ["a", "a", "b"],
            "lat": [48.85, 48.85, 48.8501],
            "lon": [2.35, 2.35, 2.3501],
            "fetched_at": pd.to_datetime(["2026-01-01T08:00Z"] * 3),
            "num_bikes_available": [1, 1, 0],
        }
    )
    out = gb.spatial_outage_redundancy(panel, radius_m=300).set_index("station_id")
    assert float(out.loc["a", "local_outage_ratio"]) == 0.0
    assert int(out.loc["a", "n_obs"]) == 1


def test_sor_is_deterministic_under_row_shuffle():
    # a duplicate (station, timestamp) must not make the result depend on row order.
    panel = pd.DataFrame(
        {
            "station_id": ["a", "b", "a", "b", "a"],
            "lat": [48.85, 48.8501, 48.85, 48.8501, 48.85],
            "lon": [2.35, 2.3501, 2.35, 2.3501, 2.35],
            "fetched_at": pd.to_datetime(
                [
                    "2026-01-01T08:00Z",
                    "2026-01-01T08:00Z",
                    "2026-01-01T09:00Z",
                    "2026-01-01T09:00Z",
                    "2026-01-01T09:00Z",
                ]
            ),
            "num_bikes_available": [0, 5, 0, 0, 2],  # duplicate (a, 09:00): 0 and 2
        }
    )
    r1 = gb.spatial_outage_redundancy(panel, radius_m=300).set_index("station_id").sort_index()
    shuffled = panel.sample(frac=1, random_state=1).reset_index(drop=True)
    r2 = gb.spatial_outage_redundancy(shuffled, radius_m=300).set_index("station_id").sort_index()
    pd.testing.assert_frame_equal(r1, r2)


def test_sor_doctest_case_unchanged():
    panel = pd.DataFrame(
        {
            "station_id": ["a", "b", "a", "b"],
            "lat": [48.8500, 48.8501, 48.8500, 48.8501],
            "lon": [2.3500, 2.3501, 2.3500, 2.3501],
            "fetched_at": pd.to_datetime(
                [
                    "2026-01-01T08:00Z",
                    "2026-01-01T08:00Z",
                    "2026-01-01T09:00Z",
                    "2026-01-01T09:00Z",
                ]
            ),
            "num_bikes_available": [0, 5, 0, 0],
        }
    )
    out = gb.spatial_outage_redundancy(panel, radius_m=300).set_index("station_id")
    assert (
        float(out.loc["a", "local_outage_ratio"]),
        float(out.loc["a", "systemic_outage_ratio"]),
    ) == (1.0, 0.5)


# --- boundary_stress --------------------------------------------------------


def test_boundary_stress_nan_capacity_is_not_virtual():
    # capacity column present but all-NaN (common GBFS) must NOT null drop-off stress.
    panel = pd.DataFrame(
        {
            "system_id": "s",
            "station_id": "a",
            "num_bikes_available": [5, 5],
            "num_docks_available": [1, 1],
            "capacity": [float("nan"), float("nan")],
        }
    )
    out = gb.boundary_stress(panel)
    assert float(out["dropoff_stress_ratio"].iloc[0]) == 1.0  # docks <= 2 both rows


def test_boundary_stress_zero_capacity_still_virtual():
    panel = pd.DataFrame(
        {
            "system_id": "s",
            "station_id": "v",
            "num_bikes_available": [0, 0],
            "num_docks_available": [0, 0],
            "capacity": [0, 0],
        }
    )
    out = gb.boundary_stress(panel)
    assert pd.isna(out["dropoff_stress_ratio"].iloc[0])


# --- offset robustness ------------------------------------------------------


def test_offset_minutes_fixed_and_nonfixed():
    assert offset_minutes("1h") == 60.0
    assert offset_minutes("30min") == 30.0
    assert offset_minutes("1D") == 1440.0
    with pytest.raises(ValueError, match="fixed-width"):
        offset_minutes("ME")


def test_service_reliability_index_rejects_non_fixed_freq():
    panel = pd.DataFrame(
        {
            "system_id": "s",
            "station_id": "a",
            "fetched_at": pd.to_datetime(["2026-01-01T08:00Z", "2026-01-02T08:00Z"]),
            "num_bikes_available": [5, 0],
            "num_docks_available": [5, 10],
        }
    )
    with pytest.raises(ValueError, match="fixed-width"):
        gb.service_reliability_index(panel, freq="ME")

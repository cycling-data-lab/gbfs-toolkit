"""Every public function must treat its input frames as read-only (no in-place mutation).

A function that silently mutates a caller's DataFrame is a classic source of
impossible-to-trace notebook bugs. This snapshots each input frame, runs the function,
and asserts the input is byte-for-byte unchanged afterwards.
"""

from __future__ import annotations

import pandas as pd
import pytest

import gbfs_toolkit as gb


def _stations() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "system_id": "s",
            "station_id": ["a", "b"],
            "station_type": ["docked_bike", "docked_bike"],
            "capacity": [20, 10],
            "lat": [48.85, 48.86],
            "lon": [2.35, 2.36],
        }
    )


def _panel() -> pd.DataFrame:
    times = pd.to_datetime(["2026-01-01T08:00Z", "2026-01-01T09:00Z", "2026-01-01T10:00Z"])
    rows = []
    for sid in ("a", "b"):
        for t, bikes in zip(times, [0, 5, 3], strict=True):
            rows.append(
                {
                    "system_id": "s",
                    "station_id": sid,
                    "fetched_at": t,
                    "num_bikes_available": bikes,
                    "num_docks_available": 10 - bikes,
                    "lat": 48.85 if sid == "a" else 48.8501,
                    "lon": 2.35 if sid == "a" else 2.3501,
                    "capacity": 10,
                }
            )
    return pd.DataFrame(rows)


def _availability() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "num_bikes_available": [0, 5, 2],
            "num_docks_available": [4, 0, 3],
            "capacity": [4, 5, 5],
        }
    )


def _vehicles_panel() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "system_id": "s",
            "vehicle_id": ["v1", "v2", "v1", "v2"],
            "lat": [48.85, 48.86, 48.85, 48.86],
            "lon": [2.35, 2.36, 2.35, 2.36],
            "fetched_at": pd.to_datetime(
                ["2026-01-01T00:00Z", "2026-01-01T00:00Z", "2026-01-20T00:00Z", "2026-01-20T00:00Z"]
            ),
        }
    )


# (label, callable) where the callable builds its own fresh inputs and runs the function.
CASES = [
    ("audit_static", lambda d: gb.audit_static(d), _stations),
    ("drop_flagged", lambda d: gb.drop_flagged(d), _stations),
    ("concentration_metrics", lambda d: gb.concentration_metrics(d), _stations),
    ("lorenz_curve", lambda d: gb.lorenz_curve(d), _stations),
    ("morans_i", lambda d: gb.morans_i(d, "capacity", k=1), _stations),
    ("occupancy", lambda d: gb.occupancy(d), _availability),
    ("station_state", lambda d: gb.station_state(d), _availability),
    ("system_profile", lambda d: gb.system_profile(d), _availability),
    ("boundary_stress", lambda d: gb.boundary_stress(d), _panel),
    ("station_outage_rates", lambda d: gb.station_outage_rates(d), _panel),
    ("service_reliability_index", lambda d: gb.service_reliability_index(d), _panel),
    ("censored_time_ratio", lambda d: gb.censored_time_ratio(d), _panel),
    ("dynamic_gini_index", lambda d: gb.dynamic_gini_index(d), _panel),
    ("calculate_net_flow", lambda d: gb.calculate_net_flow(d), _panel),
    ("cumulative_imbalance", lambda d: gb.cumulative_imbalance(d), _panel),
    ("spatial_outage_redundancy", lambda d: gb.spatial_outage_redundancy(d), _panel),
    ("coverage_report", lambda d: gb.coverage_report(d), _panel),
    ("coverage_report_system", lambda d: gb.coverage_report(d, level="system"), _panel),
    ("resample_panel", lambda d: gb.resample_panel(d), _panel),
    ("to_wide_matrix", lambda d: gb.to_wide_matrix(d), _panel),
    ("add_local_time", lambda d: gb.add_local_time(d, "Europe/Paris"), _panel),
    ("insert_explicit_gaps", lambda d: gb.insert_explicit_gaps(d), _panel),
    ("extract_snapshot_asof", lambda d: gb.extract_snapshot_asof(d, "2026-01-01T09:00Z"), _panel),
    ("filter_by_bbox", lambda d: gb.filter_by_bbox(d, (2.0, 48.0, 3.0, 49.0)), _stations),
    (
        "vehicle_id_persistence",
        lambda d: gb.vehicle_id_persistence(d, lags=("1h",)),
        _vehicles_panel,
    ),
    ("detect_ghost_vehicles", lambda d: gb.detect_ghost_vehicles(d), _vehicles_panel),
]


@pytest.mark.parametrize("label,fn,make", CASES, ids=[c[0] for c in CASES])
def test_function_does_not_mutate_input(label, fn, make):
    df = make()
    before = df.copy(deep=True)
    fn(df)
    pd.testing.assert_frame_equal(df, before, check_exact=True)

"""Tests for the pre-1.0 consolidation pass:

- pure join_availability / audit_frames (no feed object needed, offline-usable)
- presence is a fixed-category Categorical
- per-vehicle-type station counts (GBFS 2.2+/3.x)
- system pricing plans lookup
"""

import pandas as pd

from gbfs_toolkit import (
    audit_frames,
    join_availability,
    to_canonical_pricing_plans,
    to_canonical_station_info,
    to_canonical_station_status,
    to_canonical_station_vehicle_counts,
)


def _info(stations):
    return to_canonical_station_info({"data": {"stations": stations}}, system_id="x")


def _status(stations):
    return to_canonical_station_status({"data": {"stations": stations}}, system_id="x")


def test_join_availability_pure_and_categorical_presence():
    info = _info(
        [
            {"station_id": "a", "lat": 1.0, "lon": 2.0, "capacity": 10},
            {"station_id": "b", "lat": 1.1, "lon": 2.1, "capacity": 10},
        ]
    )
    status = _status([{"station_id": "a", "num_bikes_available": 4, "num_docks_available": 6}])
    av = join_availability(info, status)
    assert isinstance(av["presence"].dtype, pd.CategoricalDtype)
    assert list(av["presence"].cat.categories) == ["both", "info_only", "status_only"]
    pres = av.set_index("station_id")["presence"]
    assert pres["a"] == "both"
    assert pres["b"] == "info_only"  # in info, missing from status
    # nullable dtype preserved through the outer join
    assert av["num_bikes_available"].dtype == "Int64"


def test_audit_frames_static_only_and_with_status():
    info = _info([{"station_id": "a", "lat": 1.0, "lon": 2.0, "capacity": 10}])
    only_static = audit_frames(info)
    assert set(only_static["audit_type"]) == {"static"}

    status = _status([{"station_id": "a", "num_bikes_available": -3, "num_docks_available": 6}])
    both = audit_frames(info, status, system_id="x")
    assert set(both["audit_type"]) == {"static", "dynamic"}


def test_station_vehicle_counts_melted():
    raw = {
        "data": {
            "stations": [
                {
                    "station_id": "a",
                    "num_bikes_available": 8,
                    "vehicle_types_available": [
                        {"vehicle_type_id": "ebike", "count": 5},
                        {"vehicle_type_id": "pedal", "count": 3},
                    ],
                },
                {"station_id": "b", "num_bikes_available": 0},  # no breakdown → no rows
            ]
        }
    }
    counts = to_canonical_station_vehicle_counts(raw, system_id="x")
    assert len(counts) == 2
    assert counts["num_vehicles_available"].dtype == "Int64"
    ebike = counts[counts.vehicle_type_id == "ebike"].iloc[0]
    assert ebike["num_vehicles_available"] == 5
    assert set(counts["station_id"]) == {"a"}


def test_pricing_plans_lookup():
    raw = {
        "data": {
            "plans": [
                {
                    "plan_id": "p1",
                    "name": "Pay as you go",
                    "currency": "EUR",
                    "price": 1.5,
                    "is_taxable": True,
                }
            ]
        }
    }
    plans = to_canonical_pricing_plans(raw, system_id="x")
    row = plans.iloc[0]
    assert row["plan_id"] == "p1"
    assert row["currency"] == "EUR"
    assert row["price"] == 1.5
    assert plans["is_taxable"].dtype == "boolean"

"""Tests for fleet reconciliation across docked + free-floating feeds."""

import pandas as pd

from gbfs_toolkit import reconcile_fleet_state, to_canonical_vehicles


def _status(bikes):
    return pd.DataFrame(
        {"station_id": [f"s{i}" for i in range(len(bikes))], "num_bikes_available": bikes}
    )


def _vehicles(rows):
    # rows: list of (vehicle_id, station_id, is_disabled, is_reserved)
    return pd.DataFrame(
        rows, columns=["vehicle_id", "station_id", "is_disabled", "is_reserved"]
    ).astype({"station_id": "string", "is_disabled": "boolean", "is_reserved": "boolean"})


def test_stations_only():
    out = reconcile_fleet_state(station_status=_status([3, 4, 5]))
    assert out["available_in_stations"] == 12
    assert out["total_deployed"] == 12
    assert out["double_count_avoided"] == 0


def test_free_floating_split_by_state():
    veh = _vehicles(
        [
            ("a", None, False, False),  # free, available
            ("b", None, False, True),  # free, reserved
            ("c", None, True, False),  # free, disabled
        ]
    )
    out = reconcile_fleet_state(vehicles=veh)
    assert out["free_floating_available"] == 1
    assert out["free_floating_reserved"] == 1
    assert out["free_floating_disabled"] == 1
    assert out["total_deployed"] == 3
    assert out["total_rentable"] == 1


def test_overlap_not_double_counted():
    # 10 bikes in stations; vehicle feed lists 3 free + 2 parked-at-station (overlap)
    status = _status([6, 4])  # 10 docked
    veh = _vehicles(
        [
            ("a", None, False, False),
            ("b", None, False, False),
            ("c", None, False, False),
            ("d", "s0", False, False),  # parked at a station → overlap
            ("e", "s1", False, False),
        ]
    )
    out = reconcile_fleet_state(status, veh)
    assert out["available_in_stations"] == 10
    assert out["free_floating_available"] == 3
    assert out["docked_in_vehicle_feed"] == 2
    # the naive sum (10 + 5 = 15) double-counts the 2 docked vehicles
    assert out["total_deployed"] == 13
    assert out["double_count_avoided"] == 2


def test_reconcile_from_normalized_vehicles():
    raw = {
        "data": {
            "vehicles": [
                {"vehicle_id": "v1", "lat": 1, "lon": 2, "is_disabled": False},
                {"vehicle_id": "v2", "lat": 1, "lon": 2, "station_id": "s9"},
            ]
        }
    }
    veh = to_canonical_vehicles(raw, system_id="x")
    out = reconcile_fleet_state(vehicles=veh)
    assert out["free_floating_available"] == 1
    assert out["docked_in_vehicle_feed"] == 1

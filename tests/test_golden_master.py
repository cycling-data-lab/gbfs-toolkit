"""Golden-master regression anchors: freeze the end-to-end output on fixed inputs.

If any of these numbers change, a refactor altered behaviour. They lock the parse -> audit ->
join -> stats chain and the A1-A7 verdicts on a deterministic anomaly fixture.
"""

import pandas as pd
import pytest

import gbfs_toolkit as gb


def test_bundled_sample_pipeline_is_stable():
    info, status = gb.load_example()
    assert (len(info), len(status)) == (8, 8)

    verdict = gb.audit_static(info)
    assert int(verdict["flagged"].sum()) == 0  # the bundled central-Paris sample is clean

    av = gb.join_availability(info, status)
    av["occ"] = gb.occupancy(av)
    assert float(av["occ"].sum()) == pytest.approx(3.575195, abs=1e-5)

    profile = gb.system_profile(av)
    assert int(profile["n_stations"]) == 8
    assert float(profile["total_capacity"]) == 199.0
    assert float(profile["total_bikes_available"]) == 84.0


def _anomaly_fixture() -> pd.DataFrame:
    """Six clustered docked stations, one teleported to (0, 0), one carshare, one free-floating."""
    rows = [
        {
            "system_id": "sys",
            "station_id": f"d{i}",
            "station_type": "docked_bike",
            "capacity": 20 + i,
            "lat": 48.85 + 0.001 * i,
            "lon": 2.35 + 0.001 * i,
        }
        for i in range(6)
    ]
    rows += [
        {
            "system_id": "sys",
            "station_id": "outlier",
            "station_type": "docked_bike",
            "capacity": 20,
            "lat": 0.0,
            "lon": 0.0,
        },
        {
            "system_id": "sys",
            "station_id": "car",
            "station_type": "carsharing",
            "capacity": 5,
            "lat": 48.855,
            "lon": 2.355,
        },
        {
            "system_id": "sys",
            "station_id": "ff",
            "station_type": "free_floating",
            "capacity": None,
            "lat": 48.856,
            "lon": 2.356,
        },
    ]
    return pd.DataFrame(rows)


def test_audit_golden_master():
    verdict = gb.audit_static(_anomaly_fixture())
    flags = {f"A{i}": int(verdict[f"A{i}"].sum()) for i in range(1, 8)}
    # A1 car-share, A3 free-floating, A4 the teleported station, A5 the whole system (huge bbox).
    assert flags == {"A1": 1, "A2": 0, "A3": 1, "A4": 1, "A5": 9, "A6": 0, "A7": 0}
    by_id = verdict.set_index("station_id")
    assert by_id.loc["car", "A1"] and by_id.loc["ff", "A3"] and by_id.loc["outlier", "A4"]
    assert by_id["A5"].all()  # out-of-perimeter is a system-level flag

"""Tests (2.0.1): behaviours kept by default, with an opt-in alternative."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import gbfs_toolkit as gb


def _stuck_across_the_night():
    day1 = pd.date_range("2026-03-02T18:00Z", periods=4, freq="1h")  # 18:00 to 21:00
    day2 = pd.date_range("2026-03-03T06:00Z", periods=3, freq="1h")  # 06:00 to 08:00
    return pd.DataFrame(
        {
            "system_id": "s",
            "station_id": "a",
            "fetched_at": list(day1) + list(day2),
            "num_bikes_available": 4,
        }
    )


def test_frozen_run_default_counts_the_night_between_active_hours():
    out = gb.detect_frozen_stations(_stuck_across_the_night(), min_run_hours=6)
    assert out["longest_const_run_hours"].iloc[0] == 14.0  # 18:00 to 08:00, night included
    assert bool(out["is_frozen"].iloc[0])


def test_frozen_run_can_leave_the_night_out():
    p = _stuck_across_the_night()
    out = gb.detect_frozen_stations(p, min_run_hours=6, exclude_gaps=True)
    assert out["longest_const_run_hours"].iloc[0] == 5.0  # 3 h in the evening + 2 h in the morning
    assert not bool(out["is_frozen"].iloc[0])
    assert bool(
        gb.detect_frozen_stations(p, min_run_hours=5, exclude_gaps=True)["is_frozen"].iloc[0]
    )
    # without a gap nothing changes
    t = pd.date_range("2026-03-02T06:00Z", periods=10, freq="1h")
    flat = pd.DataFrame(
        {"system_id": "s", "station_id": "a", "fetched_at": t, "num_bikes_available": 4}
    )
    both = [gb.detect_frozen_stations(flat, exclude_gaps=x) for x in (False, True)]
    pd.testing.assert_frame_equal(both[0], both[1])


def _two_latitudes():
    rng = np.random.default_rng(0)

    def system(sid, lat0, lon0, n=60, spread=0.03):
        return pd.DataFrame(
            {
                "system_id": sid,
                "station_id": [f"{sid}{i}" for i in range(n)],
                "station_type": "docked_bike",
                "capacity": 20,
                "lat": lat0 + rng.normal(0, spread, n),
                "lon": lon0 + rng.normal(0, spread * 2, n),
            }
        )

    oslo = system("oslo", 59.9, 10.75)
    oslo.loc[len(oslo)] = ["oslo", "oslo_out", "docked_bike", 20, 59.9, 10.75 + 0.2]
    return oslo, system("quito", -0.2, -78.5)


def test_a4_default_projects_around_the_latitude_of_the_whole_input():
    oslo, quito = _two_latitudes()
    alone = gb.audit_static(oslo)
    both = gb.audit_static(pd.concat([oslo, quito], ignore_index=True))
    flagged_alone = set(alone.loc[alone["A4"], "station_id"])
    flagged_both = set(both.loc[both["A4"] & (both["system_id"] == "oslo"), "station_id"])
    # documented behaviour: a system's A4 depends on the other systems in the frame
    assert flagged_alone != flagged_both


def test_a4_per_system_projection_does_not_depend_on_the_other_systems():
    oslo, quito = _two_latitudes()
    both = gb.audit_static(pd.concat([oslo, quito], ignore_index=True), a4_projection="per_system")
    for system in (oslo, quito):
        alone = gb.audit_static(system, a4_projection="per_system")
        sid = system["system_id"].iloc[0]
        got = both[both["system_id"] == sid].reset_index(drop=True)
        pd.testing.assert_series_equal(got["A4"], alone["A4"])
    with pytest.raises(ValueError, match="a4_projection"):
        gb.audit_static(oslo, a4_projection="mercator")

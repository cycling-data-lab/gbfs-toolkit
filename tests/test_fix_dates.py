"""Regression tests (2.0.1): dates, time zones and clock changes."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import gbfs_toolkit as gb
from gbfs_toolkit.core.models import coerce_schema

# --- dates and time zones ----------------------------------------------------------


def test_simulated_last_reported_is_the_simulated_date_not_1970():
    info, status = gb.simulate_city_flows(gb.SimConfig(n_stations=5, days=1))
    lr = pd.to_datetime(status["last_reported"], unit="s", utc=True)
    assert lr.min() == pd.Timestamp("2026-06-01", tz="UTC")
    assert (lr.dt.year == 2026).all()


def test_synthetic_city_last_reported_is_not_1970():
    out = gb.simulate_city(n_stations=5, days=1)
    status = out[1] if isinstance(out, tuple) else out
    assert (pd.to_datetime(status["last_reported"], utc=True).dt.year >= 2000).all()


def test_synthetic_stations_are_not_stale_for_the_dynamic_audit():
    from gbfs_toolkit.audit.dynamic import audit_dynamic

    out = gb.simulate_city(n_stations=3, days=1)
    status = out[1] if isinstance(out, tuple) else out
    assert not audit_dynamic(status.head(6))["D3_stale"].any()


def test_coerce_schema_reads_numbers_as_unix_seconds():
    out = coerce_schema(pd.DataFrame({"last_reported": [1767225600]}), "station_status")
    assert out["last_reported"].iloc[0] == pd.Timestamp("2026-01-01", tz="UTC")


def test_diurnal_profiles_keep_the_local_hours_of_a_local_panel():
    idx = pd.date_range("2026-01-05", periods=72, freq="1h", tz="Asia/Tokyo")
    bikes = [2 if 7 <= t.hour <= 10 else 10 for t in idx]
    panel = pd.DataFrame(
        {
            "system_id": "s",
            "station_id": "a",
            "fetched_at": idx,
            "num_bikes_available": bikes,
            "num_docks_available": [12 - b for b in bikes],
        }
    )
    prof, _ = gb.diurnal_profiles(panel, min_obs=1)
    lowest = int(prof.iloc[0].idxmin()[1:])
    assert 7 <= lowest <= 10  # the UTC hour would be 22 to 01
    # a naive panel is still read as UTC
    naive = panel.assign(fetched_at=idx.tz_localize(None))
    prof_naive, _ = gb.diurnal_profiles(naive, min_obs=1)
    assert 7 <= int(prof_naive.iloc[0].idxmin()[1:]) <= 10


def test_is_holiday_matches_calendar_dates_in_a_tz_aware_panel():
    for tz in ("UTC", "Europe/Paris"):
        ts = pd.DatetimeIndex(["2026-07-14 10:00", "2026-07-15 10:00"]).tz_localize(tz)
        out = gb.temporal_context_features(
            pd.DataFrame({"fetched_at": ts}), holidays=["2026-07-14"]
        )
        assert out["is_holiday"].tolist() == [True, False]


def _dst_panel():
    t = pd.date_range("2026-10-25T00:00Z", periods=6, freq="20min").tz_convert("Europe/Paris")
    rows = []
    for s, shift in (("a", 0), ("b", 1)):
        for i, ts in enumerate(t):
            rows.append(
                {
                    "system_id": "s",
                    "station_id": s,
                    "fetched_at": ts,
                    "num_bikes_available": 3 + (i + shift) % 3,
                    "num_docks_available": 5,
                    "lat": 48.85,
                    "lon": 2.35,
                }
            )
    return pd.DataFrame(rows)


def test_hourly_bins_of_a_local_panel_survive_the_autumn_clock_change():
    from gbfs_toolkit.core.utils import floor_time

    p = _dst_panel()
    assert p["fetched_at"].dt.tz_localize(None).duplicated().any()  # 02:xx happens twice
    out = floor_time(p["fetched_at"], "1h")
    assert len(out) == len(p) and out.notna().all()
    assert out.nunique() == 2  # the two passes through 02:00 stay distinct instants


def test_functions_with_sub_daily_bins_do_not_crash_on_local_time_across_dst():
    p = _dst_panel()
    assert len(gb.turnover(p, freq="1h")) > 0
    assert len(gb.spatial_center_of_mass(p)) > 0
    gb.availability_synchrony(p, min_overlap=2)  # default freq "1h"


def test_a_single_profiled_station_is_one_cluster():
    pytest.importorskip("sklearn")
    idx = pd.date_range("2026-01-05", periods=48, freq="1h", tz="UTC")
    panel = pd.DataFrame(
        {
            "system_id": "s",
            "station_id": "a",
            "fetched_at": idx,
            "num_bikes_available": np.arange(48) % 7,
            "num_docks_available": 6 - np.arange(48) % 7,
        }
    )
    out = gb.cluster_diurnal_profiles(panel, n_clusters="auto", min_obs=12)
    assert out["cluster"].tolist() == [0]

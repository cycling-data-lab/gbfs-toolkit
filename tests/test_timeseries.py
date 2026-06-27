"""Tests for the longitudinal layer (parquet round-trip, panel dedup, net-flow)."""

import pandas as pd
import pytest

from gbfs_toolkit import append_to_parquet, build_availability_panel, calculate_net_flow

pytest.importorskip("pyarrow")


def _snapshot(system_id, bikes, fetched_at, last_reported):
    return pd.DataFrame(
        {
            "system_id": system_id,
            "station_id": ["1", "2"],
            "num_bikes_available": bikes,
            "num_docks_available": [20 - b for b in bikes],
            "last_reported": pd.to_datetime(last_reported, unit="s", utc=True),
            "fetched_at": pd.to_datetime(fetched_at, unit="s", utc=True),
            "gbfs_version": "2.3",
        }
    )


def test_append_and_build_panel_roundtrip(tmp_path):
    base = tmp_path / "lake"
    t0, t1, t2 = 1_700_000_000, 1_700_000_300, 1_700_000_600
    append_to_parquet(_snapshot("velib", [10, 5], t0, t0), base)
    append_to_parquet(_snapshot("velib", [8, 5], t1, [t1, t0]), base)  # station 2 unchanged
    append_to_parquet(_snapshot("bixi", [3, 3], t2, t2), base)

    # partition pruning by system_id
    panel = build_availability_panel(base, system_id="velib")
    assert set(panel.index.get_level_values("system_id")) == {"velib"}
    assert panel.index.names == ["system_id", "station_id", "fetched_at"]
    # station 1 changed last_reported (2 rows); station 2 unchanged → deduped (1 row)
    assert len(panel) == 3


def test_panel_dedup_on_unchanged_last_reported(tmp_path):
    base = tmp_path / "lake"
    t0, t1 = 1_700_000_000, 1_700_000_300
    # same snapshot written twice (same last_reported) → deduped
    append_to_parquet(_snapshot("velib", [10, 5], t0, t0), base)
    append_to_parquet(_snapshot("velib", [10, 5], t1, t0), base)  # identical last_reported
    panel = build_availability_panel(base, system_id="velib")
    # dedup keeps 1 row per (station, last_reported) → 2 stations
    assert len(panel) == 2


def test_net_flow_and_rebalancing(tmp_path):
    base = tmp_path / "lake"
    t0, t1, t2 = 1_700_000_000, 1_700_000_300, 1_700_000_600
    append_to_parquet(_snapshot("velib", [10, 5], t0, [t0, t0]), base)
    append_to_parquet(_snapshot("velib", [8, 5], t1, [t1, t0]), base)  # st1 −2, st2 unchanged
    append_to_parquet(_snapshot("velib", [20, 5], t2, [t2, t0]), base)  # st1 +12 → rebalancing

    panel = build_availability_panel(base, system_id="velib")
    flow = calculate_net_flow(panel, rebalancing_threshold=3)
    st1 = flow[flow.station_id == "1"].sort_values("fetched_at")
    assert st1["net_flow"].tolist()[1] == -2.0
    assert st1["net_flow"].tolist()[2] == 12.0
    assert bool(st1["is_rebalancing_suspected"].tolist()[2])
    # station 2 never changed its last_reported after t0 → deduped to 1 row, no spurious flow
    st2 = flow[flow.station_id == "2"]
    assert st2["net_flow"].abs().fillna(0).sum() == 0


def test_time_window_filter(tmp_path):
    base = tmp_path / "lake"
    t0, t1 = 1_700_000_000, 1_700_086_400  # ~1 day apart (different date partitions)
    append_to_parquet(_snapshot("velib", [10, 5], t0, t0), base)
    append_to_parquet(_snapshot("velib", [8, 4], t1, t1), base)
    only_first_day = build_availability_panel(
        base, system_id="velib", end_time=pd.Timestamp(t0 + 3600, unit="s", tz="UTC")
    )
    assert len(only_first_day) == 2  # only the t0 snapshot's 2 stations

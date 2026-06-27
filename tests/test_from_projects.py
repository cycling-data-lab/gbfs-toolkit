"""Tests for helpers distilled from the lab's research code:
frozen-station detection, flow balance, capacity-normalised turnover,
operator normalisation, and cyclical time features."""

import numpy as np
import pandas as pd

import gbfs_toolkit as gb


def _panel(rows):
    # rows: (station_id, bikes, hour) — docks = 20 - bikes, capacity 20
    base = pd.Timestamp("2026-01-05T00:00:00Z")  # a Monday
    return pd.DataFrame(
        [
            {
                "system_id": "x",
                "station_id": sid,
                "num_bikes_available": b,
                "num_docks_available": 20 - b,
                "capacity": 20,
                "fetched_at": base + pd.Timedelta(hours=h),
            }
            for sid, b, h in rows
        ]
    )


def test_detect_frozen_stations():
    # 'dead' never changes across the active day; 'alive' varies
    rows = []
    for h in range(6, 22):
        rows.append(("dead", 7, h))
        rows.append(("alive", h % 5, h))
    out = gb.detect_frozen_stations(_panel(rows), min_run_hours=6)
    assert bool(out.loc[("x", "dead"), "is_frozen"])
    assert out.loc[("x", "dead"), "frozen_value"] == 7
    assert not bool(out.loc[("x", "alive"), "is_frozen"])


def test_detect_frozen_ignores_overnight():
    # constant only outside active hours → not frozen (filtered out)
    rows = [("s", 3, h) for h in (0, 1, 2, 3, 4)] + [("s", h, h) for h in range(6, 22)]
    out = gb.detect_frozen_stations(_panel(rows), min_run_hours=6, active_hours=(6, 22))
    assert not bool(out.loc[("x", "s"), "is_frozen"])


def test_flow_balance_source_vs_sink():
    # 'source': mostly departures (outflow>inflow → balance>1); 'sink': mostly arrivals
    src = [("source", 20, 0), ("source", 4, 1), ("source", 8, 2)]  # -16, +4
    snk = [("sink", 0, 0), ("sink", 16, 1), ("sink", 12, 2)]  # +16, -4
    bal = gb.flow_balance(_panel(src + snk))
    assert bal.loc[("x", "source"), "balance"] > 1  # 16/4
    assert bal.loc[("x", "sink"), "balance"] < 1  # 4/16
    assert bal.loc[("x", "source"), "outflow"] == 16


def test_turnover_capacity_normalised():
    panel = _panel([("a", 20, 0), ("a", 10, 1), ("a", 20, 2)])  # |Δ| = 10 + 10 = 20
    tov = gb.turnover(panel, normalize="capacity")
    assert tov.iloc[0]["turnover"] == 1.0  # 20 / capacity 20


def test_normalize_operator():
    assert gb.normalize_operator("smovengo") == "Vélib' Métropole"
    assert gb.normalize_operator("Lime Paris") == "Lime"
    assert gb.normalize_operator("nextbike_warszawa") == "Nextbike"
    # unrecognised → unchanged (non-lossy), or the provided default
    assert gb.normalize_operator("some_local_coop") == "some_local_coop"
    assert gb.normalize_operator("some_local_coop", default="Other") == "Other"


def test_cyclical_time_features():
    ts = pd.to_datetime(["2026-01-01T00:00:00Z", "2026-01-01T12:00:00Z", "2026-01-01T06:00:00Z"])
    feat = gb.cyclical_time_features(ts, fields=("hour",))
    assert list(feat.columns) == ["hour_sin", "hour_cos"]
    # hour 0 → sin 0, cos 1
    assert feat.iloc[0]["hour_sin"] == 0.0
    assert feat.iloc[0]["hour_cos"] == 1.0
    # encoding is on the unit circle
    assert np.allclose(feat["hour_sin"] ** 2 + feat["hour_cos"] ** 2, 1.0)

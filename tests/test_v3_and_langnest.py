"""1.1 conformance corpus: GBFS v3 fields, language-nested feeds, and the strict /
multi-column modes of detect_frozen_stations. These structural variants are exactly what
the synthetic-only suite missed and what real-feed migration surfaced."""

import pandas as pd

from gbfs_toolkit import (
    detect_frozen_stations,
    to_canonical_station_info,
    to_canonical_station_status,
    to_canonical_vehicles,
)

# --- language-nested feeds (old v1/v2) --------------------------------------


def test_station_info_language_nested():
    raw = {
        "data": {
            "en": {"stations": [{"station_id": "a", "lat": 48.85, "lon": 2.35, "capacity": 10}]}
        }
    }
    df = to_canonical_station_info(raw, system_id="x")
    assert len(df) == 1 and df.iloc[0]["station_id"] == "a"


def test_vehicles_language_nested_bikes():
    raw = {"data": {"fr": {"bikes": [{"bike_id": "b1", "lat": 48.8, "lon": 2.3}]}}}
    df = to_canonical_vehicles(raw, system_id="x")
    assert len(df) == 1 and df.iloc[0]["vehicle_id"] == "b1"


# --- GBFS v3 field renames / additions --------------------------------------


def test_status_v3_vehicle_docks_available_fallback():
    raw = {
        "data": {
            "stations": [
                {"station_id": "a", "num_vehicles_available": 7, "vehicle_docks_available": 3}
            ]
        }
    }
    df = to_canonical_station_status(raw, system_id="x", gbfs_version="3.0")
    row = df.iloc[0]
    assert row["num_bikes_available"] == 7 and row["num_docks_available"] == 3


def test_vehicles_v3_current_fuel_percent():
    raw = {
        "data": {
            "vehicles": [{"vehicle_id": "v1", "lat": 1.0, "lon": 2.0, "current_fuel_percent": 0.8}]
        }
    }
    df = to_canonical_vehicles(raw, system_id="x", gbfs_version="3.0")
    assert "current_fuel_percent" in df.columns
    assert df.iloc[0]["current_fuel_percent"] == 0.8


# --- detect_frozen_stations: strict + multi-column --------------------------


def _panel(rows):
    base = pd.Timestamp("2026-01-05T00:00:00Z")  # active_hours=None below, so any hour is fine
    return pd.DataFrame(
        [
            {
                "system_id": "x",
                "station_id": sid,
                "num_bikes_available": b,
                "num_docks_available": d,
                "fetched_at": base + pd.Timedelta(hours=h),
            }
            for sid, b, d, h in rows
        ]
    )


def test_frozen_strict_vs_broad():
    # 'transient': bikes stuck 0..30h then changes once at 31h → broad frozen, strict NOT
    rows = [("transient", 5, 5, h) for h in range(0, 31)] + [("transient", 9, 1, 31)]
    # 'dead': bikes never change over 31h → frozen in both modes
    rows += [("dead", 7, 3, h) for h in range(0, 32)]
    panel = _panel(rows)

    broad = detect_frozen_stations(panel, min_run_hours=24, active_hours=None)
    assert bool(broad.loc[("x", "transient"), "is_frozen"])
    assert bool(broad.loc[("x", "dead"), "is_frozen"])

    strict = detect_frozen_stations(panel, min_run_hours=24, active_hours=None, strict=True)
    assert not bool(strict.loc[("x", "transient"), "is_frozen"])  # it did move
    assert bool(strict.loc[("x", "dead"), "is_frozen"])


def test_frozen_requires_all_columns():
    # bikes frozen but docks vary → frozen on bikes alone, NOT on (bikes AND docks)
    rows = [("s", 7, h % 4, h) for h in range(0, 32)]  # bikes constant, docks cycle
    panel = _panel(rows)
    one = detect_frozen_stations(
        panel, value_col="num_bikes_available", min_run_hours=24, active_hours=None
    )
    assert bool(one.loc[("x", "s"), "is_frozen"])
    both = detect_frozen_stations(
        panel,
        columns=("num_bikes_available", "num_docks_available"),
        min_run_hours=24,
        active_hours=None,
    )
    assert not bool(both.loc[("x", "s"), "is_frozen"])

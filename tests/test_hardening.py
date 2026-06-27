"""Regression tests for the v0.7 hardening batch (Gemini review):

- nullable dtypes survive the availability() outer join (no float upcast)
- new canonical fields (is_installed / current_range_meters / pricing_plan_id)
- A7 is virtual/free-float aware (no false positive on dockless systems)
- A5 bounding box is antimeridian-safe
- calculate_net_flow(account_for_system=True) mass-conservation corroboration
"""

import pandas as pd

from gbfs_toolkit import (
    GBFSFeed,
    audit_static,
    calculate_net_flow,
    to_canonical_station_status,
    to_canonical_vehicles,
)

# --- nullable dtypes + new schema fields -----------------------------------


def test_station_status_nullable_dtypes_and_is_installed():
    raw = {
        "data": {
            "stations": [{"station_id": "a", "num_bikes_available": 3, "num_docks_available": 5}]
        }
    }
    df = to_canonical_station_status(raw, system_id="x")
    assert df["num_bikes_available"].dtype == "Int64"
    assert df["is_renting"].dtype == "boolean"
    assert "is_installed" in df.columns and bool(df["is_installed"].iloc[0])


def test_vehicles_preserves_range_and_pricing():
    raw = {
        "data": {
            "vehicles": [
                {
                    "vehicle_id": "v1",
                    "lat": 1.0,
                    "lon": 2.0,
                    "current_range_meters": 8200,
                    "pricing_plan_id": "plan_a",
                }
            ]
        }
    }
    df = to_canonical_vehicles(raw, system_id="x")
    assert df["current_range_meters"].iloc[0] == 8200
    assert df["pricing_plan_id"].iloc[0] == "plan_a"
    assert df["is_reserved"].dtype == "boolean"


def _feed_with(info_stations, status_stations):
    disc = {
        "version": "2.0",
        "data": {
            "en": {
                "feeds": [
                    {"name": "station_information", "url": "info"},
                    {"name": "station_status", "url": "status"},
                ]
            }
        },
    }
    docs = {
        "gbfs": disc,
        "info": {"data": {"stations": info_stations}},
        "status": {"data": {"stations": status_stations}},
    }
    return GBFSFeed.from_url("gbfs", get_json=docs.get, system_id="x")


def test_availability_outer_join_keeps_nullable_int():
    # station b is in info but missing from status → outer join inserts pd.NA
    feed = _feed_with(
        info_stations=[
            {"station_id": "a", "lat": 1.0, "lon": 2.0, "capacity": 10},
            {"station_id": "b", "lat": 1.1, "lon": 2.1, "capacity": 10},
        ],
        status_stations=[{"station_id": "a", "num_bikes_available": 4, "num_docks_available": 6}],
    )
    av = feed.availability()
    # the bug: a float upcast would make dtype float64 and the missing value NaN
    assert av["num_bikes_available"].dtype == "Int64"
    b = av[av["station_id"] == "b"].iloc[0]
    assert pd.isna(b["num_bikes_available"])


# --- A7 virtual/free-float awareness ---------------------------------------


def _stations(n, *, system_id, station_type, capacity, virtual=False, lat0=48.85):
    return pd.DataFrame(
        {
            "system_id": system_id,
            "station_id": [f"{system_id}-{i}" for i in range(n)],
            "station_type": station_type,
            "capacity": capacity,
            "is_virtual_station": virtual,
            "lat": [lat0 + i * 1e-4 for i in range(n)],
            "lon": [2.35 + i * 1e-4 for i in range(n)],
        }
    )


def test_a7_not_fired_on_dockless_system():
    # 30 free-floating virtual anchors with null capacity — legitimate, must NOT trip A7
    ff = _stations(30, system_id="ff", station_type="free_floating", capacity=None, virtual=True)
    out = audit_static(ff)
    assert not out["A7"].any()


def test_a7_fires_on_docked_system_with_null_capacity():
    caps = [None] * 20 + [12] * 10  # 67% null among docked stations
    dock = _stations(30, system_id="dk", station_type="docked_bike", capacity=caps)
    out = audit_static(dock)
    assert out["A7"].all()


# --- A5 antimeridian safety ------------------------------------------------


def test_a5_not_fired_across_antimeridian():
    # a small system straddling +/-180 (Fiji-ish) — naive bbox would claim ~Earth-sized
    lons = [179.99, 179.995, 180.0, -179.995, -179.99]
    df = pd.DataFrame(
        {
            "system_id": "fj",
            "station_id": [f"s{i}" for i in range(len(lons))],
            "station_type": "docked_bike",
            "capacity": 10,
            "is_virtual_station": False,
            "lat": [-17.7 + i * 1e-3 for i in range(len(lons))],
            "lon": lons,
        }
    )
    out = audit_static(df)
    assert not out["A5"].any()


# --- net flow mass conservation --------------------------------------------


def _panel(rows):
    return pd.DataFrame(
        rows, columns=["system_id", "station_id", "fetched_at", "num_bikes_available"]
    )


_T0 = pd.Timestamp("2026-01-01T00:00:00Z")
_T1 = pd.Timestamp("2026-01-01T00:05:00Z")


def test_net_flow_system_corroboration_flags_injection():
    # station a +10 AND system total +10 → van injection → flagged
    panel = _panel(
        [
            ("s", "a", _T0, 5),
            ("s", "a", _T1, 15),
            ("s", "b", _T0, 5),
            ("s", "b", _T1, 5),
        ]
    )
    out = calculate_net_flow(panel, account_for_system=True)
    a1 = out[(out.station_id == "a") & (out.fetched_at == _T1)].iloc[0]
    assert a1["system_net_flow"] == 10
    assert bool(a1["is_rebalancing_suspected"])


def test_net_flow_internal_move_not_flagged_with_system_context():
    # a +10, b -10 → system flat → organic/internal, NOT a fleet change → unflagged
    panel = _panel(
        [
            ("s", "a", _T0, 5),
            ("s", "a", _T1, 15),
            ("s", "b", _T0, 15),
            ("s", "b", _T1, 5),
        ]
    )
    out = calculate_net_flow(panel, account_for_system=True)
    a1 = out[(out.station_id == "a") & (out.fetched_at == _T1)].iloc[0]
    assert a1["system_net_flow"] == 0
    assert not bool(a1["is_rebalancing_suspected"])
    # but the naive default still flags the |Δ|>3 spike
    naive = calculate_net_flow(panel)
    a1n = naive[(naive.station_id == "a") & (naive.fetched_at == _T1)].iloc[0]
    assert bool(a1n["is_rebalancing_suspected"])

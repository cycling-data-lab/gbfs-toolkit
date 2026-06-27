"""Tests for the research convenience helpers: stockout episodes, turnover,
network changes, accessibility, GeoJSON export, and the type/pricing joins."""

import pandas as pd
import pytest

import gbfs_toolkit as gb


def _panel(rows):
    # rows: (station_id, bikes, docks, minute_offset)
    base = pd.Timestamp("2026-01-01T00:00:00Z")
    return pd.DataFrame(
        [
            {
                "system_id": "x",
                "station_id": sid,
                "num_bikes_available": b,
                "num_docks_available": d,
                "fetched_at": base + pd.Timedelta(minutes=m),
            }
            for sid, b, d, m in rows
        ]
    )


def test_stockout_episodes():
    # station a: empty at t0,t5 (one episode), then refilled; full at t15
    panel = _panel(
        [
            ("a", 0, 10, 0),
            ("a", 0, 10, 5),
            ("a", 6, 4, 10),
            ("a", 10, 0, 15),
        ]
    )
    ep = gb.stockout_episodes(panel)
    empty = ep[ep.kind == "empty"]
    full = ep[ep.kind == "full"]
    assert len(empty) == 1
    assert empty.iloc[0]["duration_minutes"] == 5.0  # t0 → t5
    assert empty.iloc[0]["n_obs"] == 2
    assert len(full) == 1 and full.iloc[0]["n_obs"] == 1


def test_turnover_lower_bound_activity():
    panel = _panel([("a", 10, 0, 0), ("a", 4, 6, 5), ("a", 9, 1, 10)])
    # need last_reported absent → net_flow from diffs: -6, +5 → |Δ| sum = 11
    tov = gb.turnover(panel, freq="1D")
    assert tov.iloc[0]["turnover"] == 11.0


def test_network_changes_add_remove_recap_move():
    old = pd.DataFrame(
        {
            "system_id": "x",
            "station_id": ["keep", "gone", "recap", "move"],
            "lat": [48.85, 48.86, 48.87, 48.88],
            "lon": [2.35, 2.36, 2.37, 2.38],
            "capacity": [10, 10, 10, 10],
        }
    )
    new = pd.DataFrame(
        {
            "system_id": "x",
            "station_id": ["keep", "recap", "move", "fresh"],
            "lat": [48.85, 48.87, 48.90, 48.95],  # 'move' jumped ~2km
            "lon": [2.35, 2.37, 2.40, 2.45],
            "capacity": [10, 15, 10, 5],  # 'recap' 10→15
        }
    )
    chg = gb.network_changes(old, new).set_index(["station_id", "change"])
    assert ("fresh", "added") in chg.index
    assert ("gone", "removed") in chg.index
    assert ("recap", "recapacitated") in chg.index
    assert chg.loc[("recap", "recapacitated"), "new_value"] == 15
    assert ("move", "moved") in chg.index
    assert chg.loc[("move", "moved"), "distance_m"] > 1000


def test_stations_near_accessibility():
    info = pd.DataFrame(
        {
            "station_id": ["s1", "s2"],
            "lat": [48.8500, 48.9000],
            "lon": [2.3500, 2.4000],
        }
    )
    pois = pd.DataFrame({"name": ["clinic", "far"], "lat": [48.85040, 49.5], "lon": [2.3500, 2.4]})
    near = gb.stations_near(pois, info, radius_m=200)
    clinic = near[near.name == "clinic"].iloc[0]
    far = near[near.name == "far"].iloc[0]
    assert clinic["n_stations_within"] == 1
    assert clinic["nearest_station_id"] == "s1"
    assert far["n_stations_within"] == 0


def test_join_vehicle_types_and_pricing():
    vehicles = pd.DataFrame(
        {"vehicle_id": ["v1"], "vehicle_type_id": ["ebike"], "pricing_plan_id": ["p1"]}
    )
    types = pd.DataFrame(
        {
            "system_id": ["x"],
            "vehicle_type_id": ["ebike"],
            "form_factor": ["bicycle"],
            "propulsion_type": ["electric_assist"],
            "max_range_meters": [60000],
        }
    )
    plans = pd.DataFrame(
        {
            "system_id": ["x"],
            "plan_id": ["p1"],
            "name": ["PAYG"],
            "currency": ["EUR"],
            "price": [1.0],
            "is_taxable": [True],
            "description": [None],
        }
    )
    vt = gb.join_vehicle_types(vehicles, types)
    assert vt.iloc[0]["propulsion_type"] == "electric_assist"
    vp = gb.join_pricing(vehicles, plans)
    assert vp.iloc[0]["plan_name"] == "PAYG" and vp.iloc[0]["currency"] == "EUR"


def test_to_geojson_roundtrips():
    gpd = pytest.importorskip("geopandas")
    import json

    info = pd.DataFrame({"station_id": ["s1"], "lat": [48.85], "lon": [2.35]})
    text = gb.to_geojson(info)
    fc = json.loads(text)
    assert fc["type"] == "FeatureCollection"
    assert fc["features"][0]["properties"]["station_id"] == "s1"
    # GeoDataFrame input is passed through
    gdf = gpd.GeoDataFrame(info, geometry=gpd.points_from_xy(info.lon, info.lat), crs="EPSG:4326")
    assert "FeatureCollection" in gb.to_geojson(gdf)

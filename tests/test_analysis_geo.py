"""Tests for derived metrics, dynamic audit, geo helpers and catalogue filtering."""

import numpy as np
import pandas as pd

from gbfs_toolkit import (
    GBFSFeed,
    GeoKDTree,
    audit_dynamic,
    filter_catalog,
    find_nearest_stations,
    haversine_m,
    station_state,
)


def test_geokdtree_query_and_radius():
    # three points; query around the first
    lat = [48.85, 48.90, 49.50]
    lon = [2.35, 2.40, 3.00]
    tree = GeoKDTree(lat, lon)
    assert len(tree) == 3
    dist, idx = tree.query(48.851, 2.351, k=2)
    assert list(np.ravel(idx)) == [0, 1]
    assert np.ravel(dist)[0] < 200  # within ~150 m of point 0
    hits = tree.query_radius(48.851, 2.351, radius_m=1000)
    assert list(hits[0]) == [0]  # only the first point within 1 km


def test_geokdtree_distance_matches_haversine():
    tree = GeoKDTree([51.5074], [-0.1278])  # London
    dist, _ = tree.query(48.8566, 2.3522, k=1)  # Paris
    ref = float(haversine_m(48.8566, 2.3522, 51.5074, -0.1278))
    assert abs(float(np.ravel(dist)[0]) - ref) < 100  # agree to <100 m on ~343 km


_GBFS = {
    "version": "2.3",
    "data": {
        "en": {
            "feeds": [
                {"name": "station_information", "url": "i"},
                {"name": "station_status", "url": "s"},
            ]
        }
    },
}
_INFO = {
    "data": {
        "stations": [{"station_id": "1", "name": "A", "lat": 48.8, "lon": 2.3, "capacity": 20}]
    }
}
_STATUS = {
    "data": {
        "stations": [
            {
                "station_id": "1",
                "num_bikes_available": 7,
                "num_docks_available": 13,
                "last_reported": 1_700_000_000,
            }
        ]
    }
}


def test_feed_summary():
    feed = GBFSFeed.from_url(
        "g", system_id="demo", get_json=lambda u: {"g": _GBFS, "i": _INFO, "s": _STATUS}[u]
    )
    s = feed.summary()
    assert s["system_id"] == "demo"
    assert s["gbfs_version"] == "2.3"
    assert s["total_stations"] == 1
    assert s["total_bikes_available"] == 7
    assert "feed_staleness_min" in s


def test_station_state_categories():
    df = pd.DataFrame(
        {
            "num_bikes_available": [0, 5, 5, 0],
            "num_docks_available": [10, 0, 5, 0],
            "is_renting": [True, True, True, False],
            "is_returning": [True, True, True, False],
        }
    )
    s = station_state(df)
    assert list(s) == ["empty", "full", "normal", "disabled"]


def test_audit_dynamic_negative_overcap_stale():
    now = pd.Timestamp.now(tz="UTC")
    df = pd.DataFrame(
        {
            "station_id": ["1", "2", "3", "4"],
            "num_bikes_available": [-1, 30, 5, 5],
            "num_docks_available": [5, 30, 5, 5],
            "capacity": [20, 20, 20, 20],
            "last_reported": [now, now, now - pd.Timedelta(hours=3), now],
            "fetched_at": [now, now, now, now],
        }
    )
    v = audit_dynamic(df, stale_after_minutes=60)
    assert bool(v.loc[0, "D1_negative"])
    assert bool(v.loc[1, "D2_over_capacity"])
    assert bool(v.loc[2, "D3_stale"])
    assert not v.loc[3, "flagged"]


def test_haversine_known_distance():
    # Paris ~ London great-circle distance ≈ 343 km
    d = haversine_m(48.8566, 2.3522, 51.5074, -0.1278)
    assert 330_000 < float(d) < 360_000


def test_find_nearest_stations():
    info = pd.DataFrame(
        {
            "station_id": ["a", "b", "c"],
            "lat": [48.85, 48.90, 49.50],
            "lon": [2.35, 2.40, 3.00],
        }
    )
    near = find_nearest_stations(48.851, 2.351, info, k=2)
    assert list(near["station_id"]) == ["a", "b"]
    assert near["distance_m"].is_monotonic_increasing
    within = find_nearest_stations(48.851, 2.351, info, k=3, max_radius_m=1000)
    assert list(within["station_id"]) == ["a"]


def test_filter_catalog():
    cat = pd.DataFrame(
        {
            "system_id": ["velib", "bixi", "lyon"],
            "name": ["Vélib Métropole", "BIXI", "Vélo'v"],
            "country_code": ["FR", "CA", "FR"],
            "location": ["Paris, France", "Montreal", "Lyon, France"],
        }
    )
    fr = filter_catalog(cat, country_code="fr")
    assert set(fr["system_id"]) == {"velib", "lyon"}
    paris = filter_catalog(cat, city="paris")
    assert list(paris["system_id"]) == ["velib"]
    assert np.all(filter_catalog(cat, name="bixi")["system_id"] == ["bixi"])

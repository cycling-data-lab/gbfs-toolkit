"""Offline tests for the fetch layer (GBFSFeed + discovery), via dependency injection."""

import pytest

from gbfs_toolkit import GBFSFeed, availability, parse_discovery

# --- synthetic feeds -------------------------------------------------------

GBFS_V2 = {
    "version": "2.3",
    "data": {
        "en": {
            "feeds": [
                {"name": "station_information", "url": "http://x/info"},
                {"name": "station_status", "url": "http://x/status"},
                {"name": "free_bike_status", "url": "http://x/bikes"},
            ]
        }
    },
}

GBFS_V3 = {
    "version": "3.0",
    "data": {
        "feeds": [
            {"name": "station_information", "url": "http://y/info"},
            {"name": "station_status", "url": "http://y/status"},
            {"name": "vehicle_status", "url": "http://y/vehicles"},
        ]
    },
}

INFO = {
    "data": {
        "stations": [
            {"station_id": "1", "name": "A", "lat": 48.85, "lon": 2.35, "capacity": 20},
            {"station_id": "2", "name": "B", "lat": 48.86, "lon": 2.36, "capacity": 18},
        ]
    }
}

STATUS = {
    "data": {
        "stations": [
            {
                "station_id": "1",
                "num_bikes_available": 5,
                "num_docks_available": 15,
                "last_reported": 1_700_000_000,
            },
            {
                "station_id": "2",
                "num_bikes_available": 0,
                "num_docks_available": 18,
                "last_reported": 1_700_000_001,
            },
        ]
    }
}

BIKES = {
    "data": {
        "bikes": [
            {"bike_id": "v1", "lat": 48.8, "lon": 2.3, "is_reserved": False, "is_disabled": False},
        ]
    }
}

VEHICLES_V3 = {
    "data": {
        "vehicles": [
            {
                "vehicle_id": "v9",
                "lat": 45.0,
                "lon": 5.0,
                "is_reserved": True,
                "is_disabled": False,
            },
        ]
    }
}


def _fake_getter(mapping):
    return lambda url: mapping[url]


def test_parse_discovery_v2_and_v3():
    feeds2, ver2 = parse_discovery(GBFS_V2)
    assert ver2 == "2.3" and feeds2["free_bike_status"] == "http://x/bikes"
    feeds3, ver3 = parse_discovery(GBFS_V3)
    assert ver3 == "3.0" and "vehicle_status" in feeds3


def test_feed_discovery_and_version():
    feed = GBFSFeed.from_url("gbfs", get_json=_fake_getter({"gbfs": GBFS_V2}))
    assert feed.version == "2.3"
    assert set(feed.feeds) == {"station_information", "station_status", "free_bike_status"}
    assert feed.has("free_bike_status", "vehicle_status")


def test_station_status_and_availability_join():
    feed = GBFSFeed.from_url(
        "gbfs",
        system_id="demo",
        get_json=_fake_getter(
            {
                "gbfs": GBFS_V2,
                "http://x/info": INFO,
                "http://x/status": STATUS,
                "http://x/bikes": BIKES,
            }
        ),
    )
    status = feed.station_status()
    assert len(status) == 2
    assert status.loc[0, "num_bikes_available"] == 5
    avail = feed.availability()
    # joined: status columns + name/lat/lon/capacity/station_type from info
    assert {"num_bikes_available", "name", "capacity", "station_type"} <= set(avail.columns)
    assert avail.loc[avail.station_id == "1", "name"].iloc[0] == "A"


def test_vehicles_v2_bikes_and_v3():
    f2 = GBFSFeed.from_url("g", get_json=_fake_getter({"g": GBFS_V2, "http://x/bikes": BIKES}))
    v2 = f2.vehicles()
    assert v2.loc[0, "vehicle_id"] == "v1"
    f3 = GBFSFeed.from_url(
        "g", get_json=_fake_getter({"g": GBFS_V3, "http://y/vehicles": VEHICLES_V3})
    )
    v3 = f3.vehicles()
    assert v3.loc[0, "vehicle_id"] == "v9" and bool(v3.loc[0, "is_reserved"])


def test_snapshot_and_audit():
    feed = GBFSFeed.from_url(
        "g",
        system_id="demo",
        get_json=_fake_getter(
            {
                "g": GBFS_V2,
                "http://x/info": INFO,
                "http://x/status": STATUS,
                "http://x/bikes": BIKES,
            }
        ),
    )
    snap = feed.snapshot()
    assert set(snap) == {"information", "status", "vehicles"}
    verdict = feed.audit()
    assert "flagged" in verdict.columns and len(verdict) == 2


def test_language_setter_clears_cache():
    feed = GBFSFeed.from_url("g", get_json=_fake_getter({"g": GBFS_V2}))
    _ = feed.feeds
    feed.language = "fr"  # setter must reset discovery caches
    assert feed.language == "fr"
    assert feed._feeds is None


def test_availability_one_liner():
    df = availability(
        "g",
        system_id="demo",
        get_json=_fake_getter({"g": GBFS_V3, "http://y/info": INFO, "http://y/status": STATUS}),
    )
    assert len(df) == 2 and "num_docks_available" in df.columns


def test_missing_feed_raises():
    feed = GBFSFeed.from_url(
        "g", get_json=_fake_getter({"g": {"version": "2.0", "data": {"en": {"feeds": []}}}})
    )
    with pytest.raises(KeyError):
        feed.station_status()

"""Offline tests for the fetch layer (GBFSFeed + discovery), via dependency injection."""

import pandas as pd
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
    verdict = feed.audit()  # unified: static (2) + dynamic (2)
    assert set(verdict["audit_type"]) == {"static", "dynamic"}
    assert {"flagged", "reason", "audit_type"} <= set(verdict.columns)
    assert len(verdict) == 4


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


# --- round-2 additions -----------------------------------------------------

GBFS_FULL = {
    "version": "2.3",
    "ttl": 60,
    "last_updated": 1_700_000_500,
    "data": {
        "en": {
            "feeds": [
                {"name": "system_information", "url": "sys"},
                {"name": "station_information", "url": "info"},
                {"name": "station_status", "url": "status"},
                {"name": "vehicle_types", "url": "vtypes"},
            ]
        }
    },
}
SYSINFO = {
    "data": {
        "system_id": "demo",
        "name": "Demo Bikes",
        "timezone": "Europe/Paris",
        "language": "fr",
    }
}
VTYPES = {
    "data": {
        "vehicle_types": [
            {
                "vehicle_type_id": "e1",
                "form_factor": "bicycle",
                "propulsion_type": "electric_assist",
                "max_range_meters": 60000,
            },
        ]
    }
}
INFO_ORPHAN = {
    "data": {
        "stations": [
            {"station_id": "1", "name": "A", "lat": 48.85, "lon": 2.35, "capacity": 20},
            {"station_id": "99", "name": "InfoOnly", "lat": 48.9, "lon": 2.4, "capacity": 10},
        ]
    }
}
STATUS_ORPHAN = {
    "data": {
        "stations": [
            {
                "station_id": "1",
                "num_bikes_available": 5,
                "num_docks_available": 15,
                "last_reported": 1_700_000_000,
            },
            {
                "station_id": "42",
                "num_bikes_available": 2,
                "num_docks_available": 3,
                "last_reported": 1_700_000_000,
            },
        ]
    }
}


def _full_feed():
    return GBFSFeed.from_url(
        "g",
        system_id="demo",
        get_json=_fake_getter(
            {
                "g": GBFS_FULL,
                "sys": SYSINFO,
                "info": INFO_ORPHAN,
                "status": STATUS_ORPHAN,
                "vtypes": VTYPES,
            }
        ),
    )


def test_ttl_and_last_updated():
    feed = _full_feed()
    assert feed.ttl == 60
    assert feed.last_updated == pd.Timestamp(1_700_000_500, unit="s", tz="UTC")


def test_system_information_and_timezone():
    feed = _full_feed()
    info = feed.system_information()
    assert info["timezone"] == "Europe/Paris" and info["name"] == "Demo Bikes"
    assert feed.timezone == "Europe/Paris"


def test_vehicle_types():
    vt = _full_feed().vehicle_types()
    assert vt.loc[0, "form_factor"] == "bicycle"
    assert vt.loc[0, "propulsion_type"] == "electric_assist"
    assert vt.loc[0, "max_range_meters"] == 60000


def test_availability_outer_join_keeps_orphans():
    avail = _full_feed().availability()
    present = dict(zip(avail["station_id"], avail["presence"], strict=True))
    assert present["1"] == "both"
    assert present["42"] == "status_only"  # in status, not info
    assert present["99"] == "info_only"  # in info, not status


def test_to_local_time():
    feed = _full_feed()
    df = feed.station_status()
    local = feed.to_local_time(df, columns=("fetched_at", "last_reported"))
    assert str(local["fetched_at"].dt.tz) == "Europe/Paris"

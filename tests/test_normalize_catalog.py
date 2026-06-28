"""Tests for cross-version normalisation and catalogue resolution."""

import pandas as pd

from gbfs_toolkit import resolve, to_canonical_station_info
from gbfs_toolkit.core.models import STATION_INFO_COLUMNS


def test_normalize_v2_string_name():
    raw = {
        "data": {
            "stations": [
                {"station_id": "1", "name": "Place X", "lat": 48.8, "lon": 2.3, "capacity": 20},
            ]
        }
    }
    df = to_canonical_station_info(raw, system_id="velib")
    assert list(df.columns) == STATION_INFO_COLUMNS
    assert df.loc[0, "name"] == "Place X"
    assert df.loc[0, "system_id"] == "velib"
    assert df.loc[0, "station_type"] == "docked_bike"


def test_normalize_v3_localized_name():
    raw = {
        "data": {
            "stations": [
                {
                    "station_id": "2",
                    "name": [{"text": "Gare", "language": "fr"}],
                    "lat": 45.0,
                    "lon": 5.0,
                    "capacity": 12,
                },
            ]
        }
    }
    df = to_canonical_station_info(raw, system_id="sys", gbfs_version="3.x")
    assert df.loc[0, "name"] == "Gare"


def test_normalize_infers_free_floating_on_zero_capacity():
    raw = {"data": {"stations": [{"station_id": "3", "lat": 1.0, "lon": 2.0, "capacity": 0}]}}
    df = to_canonical_station_info(raw, system_id="ff")
    assert df.loc[0, "station_type"] == "free_floating"


def test_normalize_empty():
    df = to_canonical_station_info({"data": {"stations": []}}, system_id="x")
    assert df.empty
    assert list(df.columns) == STATION_INFO_COLUMNS


def test_resolve_from_catalog():
    cat = pd.DataFrame(
        {
            "System ID": ["velib", "bixi"],
            "Name": ["Vélib", "BIXI"],
            "Country Code": ["FR", "CA"],
            "Auto-Discovery URL": ["https://velib/gbfs.json", "https://bixi/gbfs.json"],
        }
    )
    cat.columns = [c.strip().lower().replace(" ", "_") for c in cat.columns]
    info = resolve("VELIB", cat)
    assert info["system_id"] == "velib"
    assert info["auto_discovery_url"] == "https://velib/gbfs.json"
    assert info["country_code"] == "FR"


def test_resolve_prefers_auto_discovery_over_website_url():
    # The MobilityData export ships a website ``url`` BEFORE the auto-discovery
    # column; the resolver must pick the gbfs.json, not the homepage.
    cat = pd.DataFrame(
        {
            "System ID": ["velib"],
            "Name": ["Vélib"],
            "URL": ["https://velib.example/"],  # operator website, listed first
            "Auto-Discovery URL": ["https://velib/gbfs.json"],
        }
    )
    cat.columns = [c.strip().lower().replace(" ", "_") for c in cat.columns]
    info = resolve("velib", cat)
    assert info["auto_discovery_url"] == "https://velib/gbfs.json"

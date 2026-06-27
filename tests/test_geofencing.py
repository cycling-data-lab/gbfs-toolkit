"""Tests for geofencing-zone parsing, point-in-zone joins, and equal-area density."""

import pandas as pd
import pytest

gpd = pytest.importorskip("geopandas")

from gbfs_toolkit import (  # noqa: E402
    to_canonical_geofencing,
    zone_area_km2,
    zones_for_points,
)

# Two square zones side by side near Paris; zone A forbids riding, zone B allows it.
_RAW = {
    "version": "2.3",
    "data": {
        "geofencing_zones": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [2.30, 48.85],
                                [2.32, 48.85],
                                [2.32, 48.87],
                                [2.30, 48.87],
                                [2.30, 48.85],
                            ]
                        ],
                    },
                    "properties": {
                        "name": "no-ride-zone",
                        "rules": [
                            {
                                "ride_allowed": False,
                                "ride_through_allowed": True,
                                "maximum_speed_kph": 10,
                            }
                        ],
                    },
                },
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [2.32, 48.85],
                                [2.34, 48.85],
                                [2.34, 48.87],
                                [2.32, 48.87],
                                [2.32, 48.85],
                            ]
                        ],
                    },
                    "properties": {
                        "name": "ok-zone",
                        "rules": [{"ride_allowed": True, "ride_through_allowed": True}],
                    },
                },
            ],
        }
    },
}


def test_parse_geofencing_zones():
    zones = to_canonical_geofencing(_RAW, system_id="velib")
    assert isinstance(zones, gpd.GeoDataFrame)
    assert len(zones) == 2
    assert str(zones.crs).upper().endswith("4326")
    a = zones[zones["name"] == "no-ride-zone"].iloc[0]
    assert a["ride_allowed"] is False or a["ride_allowed"] == False  # noqa: E712
    assert a["maximum_speed_kph"] == 10
    assert isinstance(a["rules"], list)


def test_parse_v3_ride_start_end_flags():
    raw = {
        "data": {
            "geofencing_zones": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
                        },
                        "properties": {
                            "name": "z",
                            "rules": [{"ride_start_allowed": False, "ride_end_allowed": True}],
                        },
                    }
                ],
            }
        }
    }
    zones = to_canonical_geofencing(raw, system_id="x", gbfs_version="3.0")
    # start disallowed → not ride-allowed overall
    assert not bool(zones.iloc[0]["ride_allowed"])


def test_empty_geofencing_returns_empty_gdf():
    zones = to_canonical_geofencing({"data": {"geofencing_zones": {"features": []}}}, system_id="x")
    assert isinstance(zones, gpd.GeoDataFrame)
    assert zones.empty


def test_zones_for_points_assigns_zone():
    zones = to_canonical_geofencing(_RAW, system_id="velib")
    # one station in each zone + one outside both
    stations = pd.DataFrame(
        {
            "station_id": ["in_a", "in_b", "outside"],
            "lat": [48.86, 48.86, 49.50],
            "lon": [2.31, 2.33, 2.33],
        }
    )
    tagged = zones_for_points(stations, zones)
    by_id = tagged.set_index("station_id")
    assert by_id.loc["in_a", "zone_name"] == "no-ride-zone"
    assert by_id.loc["in_b", "zone_name"] == "ok-zone"
    assert pd.isna(by_id.loc["outside", "zone_name"])


def test_zone_area_km2_is_metric_and_positive():
    zones = to_canonical_geofencing(_RAW, system_id="velib")
    areas = zone_area_km2(zones)
    # ~0.02° lon x 0.02° lat near 48.86°N is a few km²; sanity-bound it
    assert (areas > 0).all()
    assert (areas < 50).all()

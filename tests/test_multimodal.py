"""Tests for bikeshare ↔ transit linkage (proximity joins, BYOG GTFS stops)."""

import numpy as np
import pandas as pd
import pytest

from gbfs_toolkit import link_transit_stops

_INFO = pd.DataFrame(
    {
        "system_id": "velib",
        "station_id": ["near", "far"],
        "lat": [48.8500, 48.9000],
        "lon": [2.3500, 2.4000],
    }
)
# one GTFS stop ~50 m from "near", nothing close to "far"
_STOPS = pd.DataFrame(
    {"stop_id": ["gareA", "gareB"], "stop_lat": [48.85045, 45.0], "stop_lon": [2.3500, 5.0]}
)


def test_link_transit_feeder_flags():
    out = link_transit_stops(_INFO, _STOPS, radius_m=200)
    near = out[out.station_id == "near"].iloc[0]
    far = out[out.station_id == "far"].iloc[0]
    assert near["nearest_stop_id"] == "gareA"
    assert near["nearest_stop_dist_m"] < 200 and bool(near["is_transit_feeder"])
    assert near["n_transit_within"] == 1
    assert not bool(far["is_transit_feeder"])
    assert far["nearest_stop_dist_m"] > 1000


def test_link_transit_column_aliases():
    stops = _STOPS.rename(
        columns={"stop_lat": "latitude", "stop_lon": "longitude", "stop_id": "id"}
    )
    out = link_transit_stops(_INFO, stops, radius_m=200)
    assert out.loc[out.station_id == "near", "nearest_stop_id"].iloc[0] == "gareA"


def test_link_transit_missing_columns_raises():
    bad = pd.DataFrame({"stop_id": ["x"], "foo": [1], "bar": [2]})
    with pytest.raises(KeyError):
        link_transit_stops(_INFO, bad)


def test_link_transit_empty_stops():
    out = link_transit_stops(_INFO, _STOPS.iloc[0:0], radius_m=200)
    assert not out["is_transit_feeder"].any()
    assert np.isinf(out["nearest_stop_dist_m"]).all()

"""Tests for radius-based surroundings: features_within + station_surroundings (BYOG)."""

import numpy as np
import pandas as pd

from gbfs_toolkit import features_within, station_surroundings

_INFO = pd.DataFrame(
    {
        "system_id": "velib",
        "station_id": ["s1", "s2"],
        "lat": [48.8500, 48.9000],
        "lon": [2.3500, 2.4000],
    }
)
# POIs near s1 only: a cafe + a pharmacy ~50–80 m away; nothing near s2
_POIS = pd.DataFrame(
    {
        "amenity": ["cafe", "pharmacy", "cafe"],
        "lat": [48.85045, 48.84970, 48.8501],
        "lon": [2.3500, 2.3500, 2.3503],
    }
)
_STOPS = pd.DataFrame({"stop_id": ["m1"], "stop_lat": [48.85040], "stop_lon": [2.3500]})


def test_features_within_counts_and_categories():
    out = features_within(_INFO, _POIS, radius_m=200, category_col="amenity")
    s1 = out[out.station_id == "s1"].iloc[0]
    s2 = out[out.station_id == "s2"].iloc[0]
    assert s1["n_within"] == 3
    assert s1["n_cafe"] == 2 and s1["n_pharmacy"] == 1
    assert s1["nearest_dist_m"] < 200
    assert s2["n_within"] == 0


def test_features_within_empty_features():
    out = features_within(_INFO, _POIS.iloc[0:0], radius_m=200)
    assert (out["n_within"] == 0).all()
    assert np.isinf(out["nearest_dist_m"]).all()


def test_station_surroundings_transit_plus_pois():
    ctx = station_surroundings(
        _INFO, transit=_STOPS, osm=_POIS, radius_m=200, osm_category_col="amenity"
    )
    s1 = ctx[ctx.station_id == "s1"].iloc[0]
    # transit feeder + nearby POIs, all in one context frame
    assert bool(s1["is_transit_feeder"])
    assert s1["osm_within"] == 3
    assert "osm_cafe" in ctx.columns
    assert not bool(ctx[ctx.station_id == "s2"].iloc[0]["is_transit_feeder"])

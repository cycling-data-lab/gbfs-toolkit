"""Regression tests (2.0.1): missing values, empty inputs and index handling."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import gbfs_toolkit as gb
from gbfs_toolkit.core.models import coerce_schema

# --- missing values ---------------------------------------------------------------


def test_center_of_mass_ignores_stations_without_coordinates():
    p = pd.DataFrame(
        {
            "lat": [48.85, 48.95, np.nan],
            "lon": [2.35, 2.35, np.nan],
            "fetched_at": pd.Timestamp("2026-01-01T08:00Z"),
            "num_bikes_available": [5, 5, 10],
        }
    )
    out = gb.spatial_center_of_mass(p)
    assert out["center_lat"].iloc[0] == pytest.approx(48.90)
    assert out["center_lon"].iloc[0] == pytest.approx(2.35)


def _status_with_gap():
    a = coerce_schema(
        pd.DataFrame(
            {
                "system_id": "s",
                "station_id": ["a", "b"],
                "num_bikes_available": [0, 3],
                "num_docks_available": [5, 5],
                "fetched_at": pd.Timestamp("2026-01-01T08:00Z"),
            }
        ),
        "station_status",
    )
    b = a.copy()
    b["fetched_at"] = pd.Timestamp("2026-01-01T08:10Z")
    b["num_bikes_available"] = pd.array([pd.NA, 3], dtype="Int64")
    c = a.copy()
    c["fetched_at"] = pd.Timestamp("2026-01-01T08:20Z")
    return pd.concat([a, b, c], ignore_index=True)


def test_stockout_episodes_accepts_missing_counts():
    out = gb.stockout_episodes(_status_with_gap())
    empty = out[(out["kind"] == "empty") & (out["station_id"] == "a")]
    # the unknown reading ends the episode on both sides: two episodes, not a crash
    assert len(empty) == 2
    assert (out["station_id"] == "b").sum() == 0


def test_network_changes_accepts_nullable_capacity_with_missing_values():
    def info(cap):
        return coerce_schema(
            pd.DataFrame(
                {
                    "system_id": "s",
                    "station_id": ["a", "b"],
                    "capacity": cap,
                    "lat": [48.85, 48.86],
                    "lon": [2.35, 2.36],
                }
            ),
            "station_info",
        )

    out = gb.network_changes(info([20, None]), info([25, 10]))
    assert sorted(out["station_id"]) == ["a", "b"]
    assert set(out["change"]) == {"recapacitated"}


def test_kdtree_ignores_points_without_coordinates():
    info = pd.DataFrame(
        {
            "station_id": ["a", "b", "c"],
            "lat": [48.85, np.nan, 48.86],
            "lon": [2.35, np.nan, 2.36],
        }
    )
    near = gb.find_nearest_stations(48.85, 2.35, info, k=3)
    assert list(near["station_id"]) == ["a", "c"]
    pts = pd.DataFrame({"lat": [48.85, np.nan], "lon": [2.35, np.nan]})
    out = gb.stations_near(pts, info)
    assert out["nearest_station_id"].iloc[0] == "a"
    assert pd.isna(out["nearest_station_id"].iloc[1])
    assert np.isinf(out["nearest_station_dist_m"].iloc[1])
    assert out["n_stations_within"].tolist()[1] == 0
    tree = gb.GeoKDTree(info["lat"], info["lon"])
    assert len(tree) == 3
    assert [len(h) for h in tree.query_radius([48.85], [2.35], 5000)] == [2]


# --- inputs the docstring accepts ---------------------------------------------------


def test_extract_snapshot_asof_on_a_concatenated_panel():
    def snap(ts, v):
        return pd.DataFrame(
            {"station_id": ["a", "b"], "fetched_at": pd.Timestamp(ts), "num_bikes_available": v}
        )

    panel = pd.concat([snap("2026-01-01T07:58Z", [1, 2]), snap("2026-01-01T08:03Z", [8, 9])])
    out = gb.extract_snapshot_asof(panel, "2026-01-01T08:00Z")
    assert out.sort_values("station_id")["num_bikes_available"].tolist() == [1, 2]


def test_polls_without_last_reported_are_not_collapsed(tmp_path):
    pytest.importorskip("pyarrow")
    rows = pd.DataFrame(
        {
            "system_id": "s",
            "station_id": "a",
            "fetched_at": pd.to_datetime(
                ["2026-01-01T08:00Z", "2026-01-01T08:05Z", "2026-01-01T08:10Z"]
            ),
            "last_reported": pd.NaT,
            "num_bikes_available": [0, 1, 2],
        }
    )
    gb.append_to_parquet(rows, tmp_path)
    assert len(gb.build_availability_panel(tmp_path)) == 3


def test_numeric_looking_system_id_filter(tmp_path):
    pytest.importorskip("pyarrow")
    rows = pd.DataFrame(
        {
            "system_id": ["00123", "00123", "456"],
            "station_id": "a",
            "fetched_at": pd.to_datetime(
                ["2026-01-01T08:00Z", "2026-01-01T08:05Z", "2026-01-01T08:05Z"]
            ),
            "last_reported": pd.to_datetime(
                ["2026-01-01T07:59Z", "2026-01-01T08:04Z", "2026-01-01T08:04Z"]
            ),
            "num_bikes_available": [1, 2, 3],
        }
    )
    gb.append_to_parquet(rows, tmp_path)
    out = gb.build_availability_panel(tmp_path, system_id="00123")
    assert len(out) == 2
    assert set(out.index.get_level_values("system_id")) == {"00123"}


def test_geofencing_v3_localized_names():
    pytest.importorskip("geopandas")
    raw = {
        "data": {
            "geofencing_zones": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[[2, 48], [3, 48], [3, 49], [2, 48]]],
                        },
                        "properties": {"name": [{"text": "Service area", "language": "fr"}]},
                    }
                ],
            }
        }
    }
    out = gb.to_canonical_geofencing(raw, system_id="s")
    assert out["zone_id"].iloc[0] == "Service area"
    assert out["name"].iloc[0] == "Service area"


def test_krippendorff_alpha_with_a_non_nan_missing_sentinel():
    data = np.array([[1, 999], [1, 2]])
    assert gb.krippendorff_alpha(data, missing=999) == pytest.approx(1.0)
    labels = np.array([[1, "".join(["N", "A"])], [1, 2]], dtype=object)
    assert gb.krippendorff_alpha(labels, missing="NA") == pytest.approx(1.0)


def test_normalize_operator_splits_system_ids_on_underscores():
    assert gb.normalize_operator("lime_paris") == "Lime"
    assert gb.normalize_operator("bcycle_madison") == "BCycle"
    assert gb.normalize_operator("voi-oslo") == "Voi"
    assert gb.normalize_operator("unknown_operator") == "unknown_operator"


def test_filter_catalog_matches_text_not_regex():
    cat = pd.DataFrame(
        {"system_id": ["a", "b"], "location": ["Paris (FR)", "Lyon"], "name": ["Velib", "Velov"]}
    )
    assert list(gb.filter_catalog(cat, city="Paris (FR)")["system_id"]) == ["a"]


def test_feed_language_change_refreshes_the_system_name():
    docs = {
        "gbfs": {
            "version": "2.3",
            "data": {
                "en": {"feeds": [{"name": "system_information", "url": "si_en"}]},
                "fr": {"feeds": [{"name": "system_information", "url": "si_fr"}]},
            },
        },
        "si_en": {"data": {"system_id": "x", "name": "Bikes", "timezone": "Europe/Paris"}},
        "si_fr": {"data": {"system_id": "x", "name": "Velos", "timezone": "Europe/Paris"}},
    }
    feed = gb.GBFSFeed("gbfs", language="en", get_json=lambda u: docs[u])
    assert feed.system_information()["name"] == "Bikes"
    feed.language = "fr"
    assert feed.system_information()["name"] == "Velos"


def test_generate_gbfs_parquet_never_overwrites_the_status_file(tmp_path):
    pytest.importorskip("pyarrow")
    from gbfs_toolkit.sim.export import generate_gbfs_parquet

    target = tmp_path / "run.pq"
    meta = generate_gbfs_parquet(gb.SimConfig(n_stations=4, days=1), str(target))
    status = pd.read_parquet(target)
    assert len(status) == meta["rows"] and "num_bikes_available" in status.columns
    assert (tmp_path / "run_meta.parquet").exists()


def test_link_transit_stops_with_missing_coordinates_on_either_side():
    info = pd.DataFrame(
        {"station_id": ["a", "b"], "lat": [48.85, np.nan], "lon": [2.35, np.nan], "capacity": 10}
    )
    stops = pd.DataFrame(
        {
            "stop_id": ["s1", "s2"],
            "stop_lat": [48.851, np.nan],  # GTFS leaves it empty for some location types
            "stop_lon": [2.351, np.nan],
            "location_type": [0, 3],
        }
    )
    out = gb.link_transit_stops(info, stops)
    assert out["nearest_stop_id"].iloc[0] == "s1" and out["is_transit_feeder"].iloc[0]
    assert pd.isna(out["nearest_stop_id"].iloc[1]) and not out["is_transit_feeder"].iloc[1]
    assert (
        gb.two_step_fca(info, pd.DataFrame({"lat": [48.85], "lon": [2.35], "population": [100]}))
        .notna()
        .all()
    )

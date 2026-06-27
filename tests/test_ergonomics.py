"""Tests for the library-API conventions: sample data, show_versions, the .gbfs
accessor, schema validate/coerce, and the feed repr."""

import pandas as pd
import pytest

import gbfs_toolkit as gb


def test_load_example_returns_canonical_frames():
    info, status = gb.load_example()
    assert len(info) == 8
    assert {"station_id", "lat", "lon", "capacity"} <= set(info.columns)
    assert status["num_bikes_available"].dtype == "Int64"
    assert str(status["fetched_at"].dt.tz) == "UTC"
    # the pair joins and profiles cleanly
    av = gb.join_availability(info, status)
    assert gb.system_profile(av)["n_stations"] == 8

    with pytest.raises(ValueError, match="unknown dataset"):
        gb.load_example("atlantis")


def test_show_versions_prints(capsys):
    gb.show_versions()
    out = capsys.readouterr().out
    assert "gbfs-toolkit" in out
    assert "pandas" in out


def test_accessor_single_frame_chain():
    info, status = gb.load_example()
    av = gb.join_availability(info, status)
    # fluent chain via the registered accessor
    occ = av.gbfs.occupancy()
    assert occ.between(0, 1).all()
    verdict = info.gbfs.audit()
    assert "flagged" in verdict.columns
    # accessor result matches the free function
    pd.testing.assert_series_equal(av.gbfs.occupancy(), gb.occupancy(av))


def test_accessor_two_frame_methods():
    info, status = gb.load_example()
    av = info.gbfs.join_status(status)
    assert "presence" in av.columns
    audited = info.gbfs.audit_frames(status, system_id="paris")
    assert set(audited["audit_type"]) == {"static", "dynamic"}


def test_validate_and_coerce_schema():
    _info, status = gb.load_example()
    # validate returns the frame unchanged when columns are present
    assert gb.validate_schema(status, "station_status") is status
    with pytest.raises(gb.SchemaError):
        gb.validate_schema(status.drop(columns=["num_bikes_available"]), "station_status")
    with pytest.raises(gb.SchemaError, match="unknown schema"):
        gb.validate_schema(status, "nope")
    # coerce casts a stringy frame back to the canonical dtypes
    raw = pd.DataFrame(
        {
            "system_id": ["x"],
            "station_id": ["1"],
            "num_bikes_available": ["5"],
            "num_docks_available": ["3"],
            "is_renting": [1],
            "is_returning": [1],
            "is_installed": [1],
            "last_reported": [1_700_000_000],
            "fetched_at": [1_700_000_000],
            "gbfs_version": ["2.3"],
        }
    )
    coerced = gb.coerce_schema(raw, "station_status")
    assert coerced["num_bikes_available"].dtype == "Int64"
    assert coerced["is_renting"].dtype == "boolean"
    assert str(coerced["fetched_at"].dt.tz) == "UTC"


def test_feed_repr_no_network():
    # repr must not trigger discovery (no get_json calls here)
    feed = gb.GBFSFeed.from_url("http://example.invalid/gbfs.json", system_id="velib")
    r = repr(feed)
    assert "velib" in r and "feeds=?" in r
    assert "GBFSFeed" in feed._repr_html_()

"""Tests for the v1.7.0 io/core/interfaces consistency fixes (2nd audit pass)."""

from __future__ import annotations

import gbfs_toolkit as gb
from gbfs_toolkit.interfaces import cli


def test_numeric_vehicle_type_id_still_joins():
    # M1: a feed sending an integer vehicle_type_id must still resolve against the
    # vehicle_types lookup (previously the keys were int64 vs object and failed to join).
    vehicles = gb.to_canonical_vehicles(
        {"data": {"bikes": [{"bike_id": "b1", "vehicle_type_id": 7, "lat": 48.8, "lon": 2.3}]}},
        system_id="s",
    )
    vtypes = gb.to_canonical_vehicle_types(
        {"data": {"vehicle_types": [{"vehicle_type_id": 7, "form_factor": "bicycle"}]}},
        system_id="s",
    )
    assert str(vehicles["vehicle_type_id"].dtype) == "string"
    assert str(vtypes["vehicle_type_id"].dtype) == "string"
    joined = gb.join_vehicle_types(vehicles, vtypes)
    assert joined["form_factor"].tolist() == ["bicycle"]


def test_region_id_join_keys_are_string_on_both_sides():
    # M2: station_info.region_id and system_regions.region_id must share a dtype.
    info = gb.to_canonical_station_info(
        {"data": {"stations": [{"station_id": "a", "lat": 48.8, "lon": 2.3, "region_id": 3}]}},
        system_id="s",
    )
    regions = gb.to_canonical_system_regions(
        {"data": {"regions": [{"region_id": 3, "name": "Centre"}]}}, system_id="s"
    )
    assert str(info["region_id"].dtype) == "string"
    assert str(regions["region_id"].dtype) == "string"
    merged = info.merge(regions, on="region_id", how="left", suffixes=("", "_region"))
    assert merged["name_region"].tolist() == ["Centre"] or merged["name"].tolist() == ["Centre"]


def test_cli_exits_cleanly_on_missing_file(capsys):
    # M4: a missing input file yields a one-line stderr message and exit code 2,
    # not a raw Python traceback.
    rc = cli.main(["audit", "/no/such/file_xyz.json", "--json"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "gbfs:" in err and "file" in err.lower()

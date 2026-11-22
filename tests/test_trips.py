"""trips: publisher formats into one schema, time zones, privacy, files and zips."""

from __future__ import annotations

import io
import zipfile

import pandas as pd
import pytest

from gbfs_toolkit.trips import (
    FORMATS,
    TRIP_COLUMNS,
    TripFormat,
    detect_format,
    iter_trips,
    normalize_trips,
    read_trips,
)

MODERN = pd.DataFrame(
    {
        "ride_id": ["A1", "A2"],
        "rideable_type": ["classic_bike", "electric_bike"],
        "started_at": ["2025-01-10 08:00:00", "2025-01-10 09:00:00.250"],
        "ended_at": ["2025-01-10 08:10:00", "2025-01-10 09:30:00"],
        "start_station_name": ["Gare", "Port"],
        "start_station_id": ["S1", "S2"],
        "end_station_name": ["Port", None],
        "end_station_id": ["S2", None],
        "start_lat": [41.9, 41.8],
        "start_lng": [-87.6, -87.7],
        "end_lat": [41.8, None],
        "end_lng": [-87.7, None],
        "member_casual": ["member", "casual"],
    }
)


def test_modern_lyft_file():
    out = normalize_trips(MODERN, tz="America/Chicago", network="divvy", source_file="202501.csv")
    assert list(out.columns) == TRIP_COLUMNS
    assert out["started_at"].iloc[0] == pd.Timestamp("2025-01-10 14:00:00", tz="UTC")  # CST = UTC-6
    assert out["duration_s"].tolist() == [600.0, 1800 - 0.25]
    assert out["member_type"].tolist() == ["member", "casual"]
    assert out["end_station_id"].isna().tolist() == [
        False,
        True,
    ]  # a trip without a docking station
    assert out["end_lat"].isna().tolist() == [False, True]
    assert (out["network"] == "divvy").all() and (out["source_file"] == "202501.csv").all()
    assert out["started_at_tz_flag"].isna().all()


LEGACY = pd.DataFrame(
    {
        "tripduration": [754, 300],
        "starttime": ["2019-06-01 07:00:00", "2019-06-01 07:05:00"],
        "stoptime": ["2019-06-01 07:12:34", "2019-06-01 07:10:00"],
        "start station id": [72, 79],
        "start station name": ["W 52 St", "Franklin St"],
        "start station latitude": [40.76, 40.71],
        "start station longitude": [-73.99, -74.01],
        "end station id": [79.0, 3002.0],
        "end station name": ["Franklin St", "X"],
        "end station latitude": [40.71, 40.7],
        "end station longitude": [-74.01, -74.0],
        "bikeid": [1, 2],
        "usertype": ["Subscriber", "Customer"],
        "birth year": [1980, 1990],
        "gender": [1, 2],
    }
)


def test_legacy_lyft_file_drops_personal_fields_and_keeps_ids_whole():
    out = normalize_trips(LEGACY, tz="America/New_York")
    assert {"birth year", "gender", "bikeid", "birth_year", "bike_id"}.isdisjoint(out.columns)
    assert out["duration_s"].tolist() == [
        754.0,
        300.0,
    ]  # published duration wins over end - start (754 vs 754)
    assert out["member_type"].tolist() == ["member", "casual"]
    assert out["end_station_id"].tolist() == ["79", "3002"]  # not "79.0"
    assert out["start_station_id"].tolist() == ["72", "79"]


def test_other_lyft_family_layouts():
    divvy = pd.DataFrame(
        {
            "trip_id": [1],
            "start_time": ["1/2/2019 3:04"],
            "end_time": ["1/2/2019 3:14"],
            "from_station_id": [5],
            "from_station_name": ["A"],
            "to_station_id": [6],
            "to_station_name": ["B"],
            "usertype": ["Customer"],
            "tripduration": ["600"],
        }
    )
    d = normalize_trips(divvy, tz="America/Chicago")
    assert d["start_station_id"].iloc[0] == "5" and d["end_station_name"].iloc[0] == "B"
    cabi = pd.DataFrame(
        {
            "Duration": [120],
            "Start date": ["2018-05-01 10:00:00"],
            "End date": ["2018-05-01 10:02:00"],
            "Start station number": [31000],
            "Start station": ["X"],
            "End station number": [31001],
            "End station": ["Y"],
            "Bike number": ["W1"],
            "Member type": ["Member"],
        }
    )
    c = normalize_trips(cabi, tz="America/New_York")
    assert c["member_type"].iloc[0] == "member" and c["end_station_id"].iloc[0] == "31001"
    assert detect_format(list(cabi.columns)) == "lyft"


def test_urban_sharing_times_carry_their_offset():
    raw = pd.DataFrame(
        {
            "started_at": ["2024-10-27 01:30:00+00:00", "2024-07-01T10:00:00.000+02:00"],
            "ended_at": ["2024-10-27 01:45:00+00:00", "2024-07-01T10:20:00.000+02:00"],
            "duration": [900, 1200],
            "start_station_id": [1, 2],
            "start_station_name": ["A", "B"],
            "start_station_description": ["x", "y"],
            "start_station_latitude": [59.9, 59.91],
            "start_station_longitude": [10.7, 10.71],
            "end_station_id": [2, 1],
            "end_station_name": ["B", "A"],
            "end_station_latitude": [59.91, 59.9],
            "end_station_longitude": [10.71, 10.7],
        }
    )
    out = normalize_trips(raw)  # no tz needed
    assert out["started_at"].iloc[1] == pd.Timestamp("2024-07-01 08:00:00", tz="UTC")
    assert (
        out["ride_id"].isna().all()
        and out["member_type"].isna().all()
        and out["rideable_type"].isna().all()
    )
    assert out["duration_s"].tolist() == [900.0, 1200.0]
    assert out["start_lat"].iloc[0] == 59.9


def test_bts_recomputes_duration_and_maps_classes():
    raw = pd.DataFrame(
        {
            "trip_id": [1, 2],
            "duration": [10, 99999],
            "start_time": ["2024-04-01 08:00:00"] * 2,
            "end_time": ["2024-04-01 08:10:00", "2024-04-01 09:00:00"],
            "start_station": [3004, 3005],
            "start_lat": [39.9, 39.95],
            "start_lon": [-75.1, -75.2],
            "end_station": [3005, 3004],
            "end_lat": [39.95, 39.9],
            "end_lon": [-75.2, -75.1],
            "bike_id": [1, 2],
            "plan_duration": [0, 30],
            "trip_route_category": ["One Way"] * 2,
            "passholder_type": ["Indego30", "Walk-up"],
            "bike_type": ["electric", "standard"],
        }
    )
    out = normalize_trips(raw, tz="America/New_York")
    assert out["duration_s"].tolist() == [600.0, 3600.0]  # the published unit is not trusted
    assert out["member_type"].tolist() == ["member", "casual"]
    assert out["rideable_type"].tolist() == ["electric_bike", "classic_bike"]
    assert out["start_lng"].iloc[0] == -75.1 and out["start_station_id"].tolist() == [
        "3004",
        "3005",
    ]
    assert "bike_id" not in out.columns


def test_tz_is_required_when_times_are_local():
    with pytest.raises(ValueError, match="tz="):
        normalize_trips(MODERN)
    with pytest.raises(ValueError):
        normalize_trips(MODERN, tz="Nowhere/City")


def test_clock_changes_are_flagged_not_hidden():
    raw = pd.DataFrame(
        {
            "ride_id": ["spring", "autumn", "normal"],
            "started_at": ["2024-03-10 02:30:00", "2024-11-03 01:30:00", "2024-06-01 12:00:00"],
            "ended_at": ["2024-03-10 03:15:00", "2024-11-03 01:45:00", "2024-06-01 12:10:00"],
        }
    )
    out = normalize_trips(raw, tz="America/New_York").set_index("ride_id")
    assert out.loc["spring", "started_at_tz_flag"] == "nonexistent"
    assert out.loc["autumn", "started_at_tz_flag"] == "ambiguous"
    assert pd.isna(out.loc["normal", "started_at_tz_flag"])
    assert out.loc["autumn", "started_at"] == pd.Timestamp(
        "2024-11-03 06:30:00", tz="UTC"
    )  # the standard-time one
    assert out.loc["spring", "started_at"] == pd.Timestamp(
        "2024-03-10 07:00:00", tz="UTC"
    )  # shifted to 03:00 local, the first real instant
    assert out.loc["normal", "started_at"] == pd.Timestamp("2024-06-01 16:00:00", tz="UTC")


def test_unreadable_start_times_are_dropped_and_others_kept(caplog):
    raw = pd.DataFrame(
        {
            "ride_id": ["a", "b"],
            "started_at": ["garbage", "2025-01-01 10:00:00"],
            "ended_at": ["2025-01-01 10:05:00", None],
        }
    )
    with caplog.at_level("WARNING", logger="gbfs_toolkit"):
        out = normalize_trips(raw, tz="UTC")
    assert out["ride_id"].tolist() == ["b"] and pd.isna(out["duration_s"].iloc[0])
    assert "dropped" in caplog.text


def test_format_selection_errors_and_custom_format():
    with pytest.raises(ValueError, match="cannot tell"):
        normalize_trips(pd.DataFrame({"a": [1]}), tz="UTC")
    with pytest.raises(ValueError, match="unknown trip format"):
        normalize_trips(MODERN, "velomagg", tz="UTC")
    with pytest.raises(ValueError, match="must name"):
        TripFormat("x", {"ride_id": ["id"]})
    with pytest.raises(ValueError, match="unknown common column"):
        TripFormat("x", {"started_at": ["a"], "ended_at": ["b"], "user_id": ["u"]})
    assert "velomagg" not in FORMATS  # no format is invented
    fmt = TripFormat(
        "minutes",
        {"started_at": ["t0"], "ended_at": ["t1"], "ride_id": ["id"]},
        duration_alias=["dur_min"],
        duration_scale=60.0,
    )
    raw = pd.DataFrame(
        {"id": [9], "t0": ["2025-01-01 10:00"], "t1": ["2025-01-01 10:30"], "dur_min": [31]}
    )
    assert normalize_trips(raw, fmt, tz="Europe/Paris")["duration_s"].iloc[0] == 1860.0


def test_input_is_not_modified():
    before = MODERN.copy()
    normalize_trips(MODERN, tz="UTC")
    pd.testing.assert_frame_equal(MODERN, before)


def csv_bytes(df):
    return df.to_csv(index=False).encode()


def test_read_csv_zip_nested_zip_and_chunks(tmp_path):
    (tmp_path / "plain.csv").write_bytes(csv_bytes(MODERN))
    plain = read_trips(tmp_path / "plain.csv", tz="America/Chicago", network="n")
    assert len(plain) == 2 and plain["source_file"].iloc[0] == "plain.csv"
    assert plain["end_station_id"].isna().tolist() == [False, True]  # empty cells stay empty
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as z:
        z.writestr("202502.csv", csv_bytes(MODERN))
    outer = tmp_path / "year.zip"
    with zipfile.ZipFile(outer, "w") as z:
        z.writestr("202501.csv", csv_bytes(MODERN))
        z.writestr("nested.zip", inner.getvalue())
        z.writestr("__MACOSX/._junk.csv", b"junk")
        z.writestr("readme.txt", b"ignore me")
    out = read_trips(outer, tz="America/Chicago", chunksize=1)
    assert len(out) == 4
    assert sorted(out["source_file"].unique()) == [
        "year.zip::202501.csv",
        "year.zip::nested.zip::202502.csv",
    ]
    assert [len(c) for c in iter_trips(outer, tz="America/Chicago", chunksize=1)] == [1, 1, 1, 1]
    assert (
        read_trips(io.BytesIO(csv_bytes(MODERN)), tz="UTC", network="s")["source_file"].iloc[0]
        == "<stream>"
    )


def test_empty_file_gives_an_empty_frame_with_the_schema(tmp_path):
    (tmp_path / "e.zip").write_bytes(b"")
    with zipfile.ZipFile(tmp_path / "e.zip", "w"):
        pass
    out = read_trips(tmp_path / "e.zip", tz="UTC")
    assert out.empty and list(out.columns) == TRIP_COLUMNS

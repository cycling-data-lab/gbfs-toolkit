"""store: the partitioned lake, harmonised names, local time, DuckDB views."""

from __future__ import annotations

import pandas as pd
import pytest

from gbfs_toolkit.core.errors import GBFSValidationError
from gbfs_toolkit.core.models import SchemaError
from gbfs_toolkit.store import (
    duckdb_view_sql,
    harmonize,
    list_partitions,
    read_lake,
    read_lake_metadata,
    register_duckdb_views,
    write_lake,
)

pytest.importorskip("pyarrow")


def raw(times, system="a", station="s1", bikes=3):
    n = len(times)
    return pd.DataFrame(
        {
            "system_id": system,
            "station_id": station,
            "fetched_at": pd.to_datetime(times, utc=True),
            "num_bikes_available": pd.array([bikes] * n, dtype="Int64"),
            "num_docks_available": pd.array([5] * n, dtype="Int64"),
        }
    )


def test_harmonize_renames_types_and_keeps_missing_values():
    df = pd.DataFrame(
        {
            "station_id": [1, 2],
            "fetched_at": ["2026-07-01T10:00:00Z", "2026-07-01T10:00:00Z"],
            "last_reported": [1782900000, None],
            "num_bikes_available": [2.0, None],
            "is_renting": [True, None],
            "extra": ["x", "y"],
        }
    )
    out = harmonize(df, system_id="demo")
    assert list(out.columns)[:4] == [
        "observed_at_utc",
        "system_id",
        "station_id",
        "num_bikes_available",
    ]
    assert out["observed_at_utc"].dt.tz is not None and "fetched_at" not in out.columns
    assert out["num_bikes_available"].dtype == "Int64" and out[
        "num_bikes_available"
    ].isna().tolist() == [False, True]
    assert out["is_renting"].dtype == "boolean" and out["is_renting"].isna().tolist() == [
        False,
        True,
    ]
    assert out["station_id"].tolist() == ["1", "2"] and out["extra"].tolist() == ["x", "y"]
    assert out["last_reported_utc"].isna().tolist() == [False, True]
    assert "fetched_at" in df.columns  # the input is untouched


def test_harmonize_local_time_follows_the_clock_change():
    t = ["2026-03-29T00:30:00Z", "2026-03-29T01:30:00Z"]  # Paris springs forward at 01:00 UTC
    out = harmonize(raw(t), tz="Europe/Paris")
    assert out["utc_offset_min"].tolist() == [60, 120]
    assert out["observed_at_local"].dt.hour.tolist() == [1, 3]
    per_system = harmonize(pd.concat([raw(t[:1]), raw(t[:1], system="b")]), tz={"a": "Asia/Tokyo"})
    assert per_system["utc_offset_min"].iloc[0] == 540 and pd.isna(
        per_system["utc_offset_min"].iloc[1]
    )
    with pytest.raises(Exception, match="Nowhere"):
        harmonize(raw(t), tz="Nowhere/City")


def test_harmonize_errors():
    with pytest.raises(ValueError):
        harmonize(raw(["2026-01-01"]), kind="trips")
    with pytest.raises(SchemaError):
        harmonize(raw(["2026-01-01"]).drop(columns="system_id"))
    with pytest.raises(SchemaError):
        harmonize(raw(["2026-01-01"]).rename(columns={"fetched_at": "t"}))


def test_write_splits_by_system_and_utc_month_and_reads_back(tmp_path):
    df = harmonize(
        pd.concat(
            [
                raw(["2026-01-31T23:59Z", "2026-02-01T00:01Z"]),
                raw(["2026-02-03T00:00Z"], system="b"),
            ]
        )
    )
    touched = write_lake(df, tmp_path, timezones={"a": "Europe/Paris"})
    assert touched[["system_id", "year", "month", "rows"]].values.tolist() == [
        ["a", 2026, 1, 1],
        ["a", 2026, 2, 1],
        ["b", 2026, 2, 1],
    ]
    assert (tmp_path / "system_id=a" / "year=2026" / "month=01").is_dir()
    back = read_lake(tmp_path)
    assert len(back) == 3 and back["system_id"].dtype in ("object", "string", "str")
    assert read_lake_metadata(tmp_path)["timezones"] == {"a": "Europe/Paris"}
    parts = list_partitions(tmp_path)
    assert parts["files"].tolist() == [1, 1, 1] and parts["bytes"].gt(0).all()


def test_read_filters_systems_window_and_columns(tmp_path):
    times = pd.date_range("2026-01-30T00:00Z", periods=6, freq="1D")
    write_lake(harmonize(pd.concat([raw(times), raw(times, system="b")])), tmp_path)
    only_a = read_lake(tmp_path, systems=["a"])
    assert set(only_a["system_id"]) == {"a"} and len(only_a) == 6
    window = read_lake(tmp_path, start="2026-02-01", end="2026-02-03")
    assert sorted(window["observed_at_utc"].unique()) == list(
        pd.to_datetime(["2026-02-01", "2026-02-02"], utc=True)
    )
    assert len(window) == 4  # two days, two systems
    cols = read_lake(tmp_path, columns=["station_id"], start="2026-02-01")
    assert list(cols.columns) == ["station_id"]
    assert read_lake(tmp_path, end="2026-01-30").empty
    assert read_lake(tmp_path / "nothing").empty


def test_numeric_looking_system_ids_stay_text(tmp_path):
    write_lake(harmonize(raw(["2026-03-01"], system="007")), tmp_path)
    assert read_lake(tmp_path, systems=["007"])["system_id"].tolist() == ["007"]


def test_modes_append_merge_replace(tmp_path):
    first = harmonize(raw(["2026-03-01T10:00Z", "2026-03-01T10:01Z"]))
    second = harmonize(raw(["2026-03-01T10:01Z", "2026-03-01T10:02Z"]))
    write_lake(first, tmp_path)
    write_lake(second, tmp_path)  # append: nothing lost, duplicates kept
    assert len(read_lake(tmp_path)) == 4
    assert list_partitions(tmp_path)["files"].iloc[0] == 2
    write_lake(second, tmp_path, mode="merge")  # combine, drop exact duplicates, one file
    merged = read_lake(tmp_path)
    assert len(merged) == 3 and list_partitions(tmp_path)["files"].iloc[0] == 1
    write_lake(first, tmp_path, mode="replace")
    assert len(read_lake(tmp_path)) == 2
    with pytest.raises(ValueError):
        write_lake(first, tmp_path, mode="overwrite")


def test_no_temporary_files_are_left_and_bad_system_id_is_refused(tmp_path):
    write_lake(harmonize(raw(["2026-03-01"])), tmp_path)
    assert not [p for p in tmp_path.rglob("*") if p.name.endswith(".tmp")]
    with pytest.raises(ValueError, match="folder name"):
        write_lake(harmonize(raw(["2026-03-01"], system="../x")), tmp_path)


def test_a_foreign_parquet_layout_is_reported(tmp_path):
    pd.DataFrame({"x": [1]}).to_parquet(tmp_path / "flat.parquet")
    with pytest.raises(GBFSValidationError, match="layout"):
        read_lake(tmp_path)


def test_duckdb_view_sql_is_plain_and_quotes_paths():
    sql = duckdb_view_sql("/tmp/it's/lake", "v1")
    assert "it''s" in sql and "hive_partitioning = true" in sql
    with pytest.raises(ValueError):
        duckdb_view_sql("/x", "bad name; drop table")


def test_duckdb_views_query_the_lake(tmp_path):
    duckdb = pytest.importorskip("duckdb")
    times = pd.date_range("2026-01-30T00:00Z", periods=4, freq="1D")
    write_lake(harmonize(pd.concat([raw(times), raw(times, system="007")])), tmp_path)
    con = duckdb.connect()
    assert register_duckdb_views(con, {"station_status": tmp_path}) == ["station_status"]
    n = con.execute(
        "SELECT count(*) FROM station_status WHERE system_id = '007' AND month = 2"
    ).fetchone()[0]
    assert n == 2
    assert con.execute(
        "SELECT typeof(year), typeof(system_id) FROM station_status LIMIT 1"
    ).fetchone() == ("INTEGER", "VARCHAR")

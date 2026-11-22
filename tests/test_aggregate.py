"""aggregate: fixed definitions, conservation of observations, time zones."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from gbfs_toolkit.aggregate import (
    AGGREGATE_COLUMNS,
    aggregate_availability,
    check_conservation,
)
from gbfs_toolkit.core.errors import GBFSValidationError
from gbfs_toolkit.core.models import SchemaError


def frame(bikes, docks=None, *, start="2026-03-01T08:00Z", every="1min", station="s", system="a"):
    n = len(bikes)
    df = pd.DataFrame(
        {
            "system_id": system,
            "station_id": station,
            "fetched_at": pd.date_range(start, periods=n, freq=every),
            "num_bikes_available": pd.array(bikes, dtype="Int64"),
        }
    )
    if docks is not None:
        df["num_docks_available"] = pd.array(docks, dtype="Int64")
    return df


def test_definitions_on_a_hand_computed_bucket():
    df = frame([0, 2, 4, 0], [10, 8, 6, 10], station="s")
    df["is_renting"] = pd.array([True, True, False, True], dtype="boolean")
    row = aggregate_availability(df, "1h").iloc[0]
    assert row["n_obs"] == 4 and row["n_valid"] == 4
    assert row["bikes_mean"] == 1.5 and row["bikes_min"] == 0 and row["bikes_max"] == 4
    assert row["bikes_first"] == 0 and row["bikes_last"] == 0
    assert row["docks_mean"] == 8.5 and row["docks_min"] == 6
    assert row["pct_empty"] == 50.0 and row["pct_full"] == 0.0 and row["pct_renting"] == 75.0
    assert row["movement_volume"] == 2 + 2 + 4  # |2-0| + |4-2| + |0-4|
    assert np.isnan(row["pct_both_zero"])  # no both_zero_suspect column


def test_buckets_are_aligned_on_utc_and_sorted():
    df = frame([1] * 40, start="2026-03-01T08:07Z")
    agg = aggregate_availability(df, "15min")
    assert agg["bucket_start_utc"].dt.minute.tolist() == [0, 15, 30, 45]
    assert agg["n_obs"].tolist() == [8, 15, 15, 2]


def test_full_uses_docks_then_capacity():
    df = frame([5, 5], [0, 3])
    assert aggregate_availability(df, "1h")["pct_full"].iloc[0] == 50.0
    nodocks = frame([10, 4])
    nodocks["capacity"] = 10
    assert aggregate_availability(nodocks, "1h")["pct_full"].iloc[0] == 50.0
    neither = frame([10, 4])
    assert np.isnan(aggregate_availability(neither, "1h")["pct_full"].iloc[0])


def test_suspect_rows_are_counted_but_leave_every_other_column():
    df = frame([3, 0, 0, 3], [1, 0, 0, 1])
    df["both_zero_suspect"] = pd.array([False, True, True, False], dtype="boolean")
    row = aggregate_availability(df, "1h").iloc[0]
    assert row["n_obs"] == 4 and row["n_valid"] == 2 and row["pct_both_zero"] == 50.0
    assert row["bikes_mean"] == 3.0 and row["pct_empty"] == 0.0
    assert pd.isna(row["movement_volume"]) or row["movement_volume"] == 0
    # the 0 -> 3 step is not counted: its predecessor is suspect


def test_pairs_need_consecutive_valid_rows_within_the_gap():
    t = pd.to_datetime(
        ["2026-03-01T08:00Z", "2026-03-01T08:01Z", "2026-03-01T08:10Z", "2026-03-01T08:11Z"]
    )
    df = pd.DataFrame(
        {"system_id": "a", "station_id": "s", "fetched_at": t, "num_bikes_available": [1, 4, 9, 10]}
    )
    assert (
        aggregate_availability(df, "1h")["movement_volume"].iloc[0] == 3 + 1
    )  # the 8-minute jump is skipped
    wide = aggregate_availability(df, "1h", max_pair_gap="15min")
    assert wide["movement_volume"].iloc[0] == 3 + 5 + 1


def test_missing_counts_are_missing_not_zero():
    df = frame([None, None, 4])
    row = aggregate_availability(df, "1h").iloc[0]
    assert row["n_obs"] == 3 and row["n_valid"] == 1 and row["bikes_mean"] == 4.0
    allna = aggregate_availability(frame([None, None]), "1h").iloc[0]
    assert allna["n_valid"] == 0 and np.isnan(allna["bikes_mean"]) and pd.isna(allna["bikes_min"])


def test_stations_and_systems_are_separate_groups():
    a, b = frame([1, 2], station="s1"), frame([5, 6], station="s2", system="b")
    agg = aggregate_availability(pd.concat([b, a]), "1h")
    assert agg[["system_id", "station_id"]].values.tolist() == [["a", "s1"], ["b", "s2"]]
    assert agg["movement_volume"].tolist() == [1, 1]


def test_local_time_columns_and_clock_change():
    t = pd.date_range(
        "2026-03-29T00:00Z", periods=4, freq="1h"
    )  # Paris springs forward at 01:00 UTC
    df = pd.DataFrame(
        {
            "system_id": ["a", "a", "b", "b"],
            "station_id": "s",
            "fetched_at": t,
            "num_bikes_available": 1,
        }
    )
    agg = aggregate_availability(df, "1h", tz={"a": "Europe/Paris", "b": "UTC"})
    assert agg["utc_offset_min"].tolist() == [60, 120, 0, 0]
    assert agg["bucket_start_local"].dt.hour.tolist() == [1, 3, 2, 3]
    assert agg["bucket_start_local"].dt.tz is None
    assert "bucket_start_local" not in aggregate_availability(df, "1h").columns


def test_input_is_not_modified_and_errors_are_clear():
    df = frame([1, 2, 3])
    before = df.copy()
    aggregate_availability(df, "15min")
    pd.testing.assert_frame_equal(df, before)
    with pytest.raises(ValueError, match="fixed-width"):
        aggregate_availability(df, "1ME")
    with pytest.raises(SchemaError):
        aggregate_availability(df.drop(columns="station_id"), "1h")
    empty = aggregate_availability(df.iloc[0:0], "1h")
    assert empty.empty and set(empty.columns) <= set(AGGREGATE_COLUMNS)


def test_naive_and_non_utc_times_are_read_correctly():
    df = frame([1, 2])
    local = df.copy()
    local["fetched_at"] = local["fetched_at"].dt.tz_convert("Europe/Paris")
    naive = df.copy()
    naive["fetched_at"] = naive["fetched_at"].dt.tz_localize(None)
    base = aggregate_availability(df, "1h")
    pd.testing.assert_frame_equal(base, aggregate_availability(local, "1h"))
    pd.testing.assert_frame_equal(base, aggregate_availability(naive, "1h"))


def test_check_conservation_catches_a_loss():
    df = frame([1] * 30)
    agg = aggregate_availability(df, "15min")
    check_conservation(agg, df)
    with pytest.raises(GBFSValidationError, match="conserve"):
        check_conservation(agg.iloc[:-1], df)

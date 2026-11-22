"""quality: coverage, gaps, silent feeds, incident registry and the row-level indicators."""

from __future__ import annotations

import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from gbfs_toolkit.core.errors import GBFSValidationError
from gbfs_toolkit.core.models import SchemaError
from gbfs_toolkit.quality import (
    COVERAGE_COLUMNS,
    INCIDENT_COLUMNS,
    add_incident,
    add_quality_indicators,
    assess,
    daily_coverage,
    detect_incidents,
    field_unsupported_by_operator,
    find_collector_gaps,
    find_silent_feeds,
    incident_registry,
    incidents_overlapping,
    read_incidents,
    write_incidents,
)


def minutes(start: str, n: int, system: str, every: int = 1) -> pd.DataFrame:
    t = pd.date_range(start, periods=n, freq=f"{every}min", tz="UTC")
    return pd.DataFrame({"system_id": system, "station_id": "s", "fetched_at": t})


def status_of(cov: pd.DataFrame, system: str) -> list[str]:
    return cov[cov["system_id"] == system].sort_values("date_utc")["status"].tolist()


def test_full_day_is_ok_and_partial_day_is_partial():
    snaps = pd.concat([minutes("2026-03-01", 1440, "a"), minutes("2026-03-01", 800, "b")])
    cov = daily_coverage(snaps)
    assert list(cov.columns) == COVERAGE_COLUMNS
    assert status_of(cov, "a") == ["ok"] and status_of(cov, "b") == ["partial"]
    b = cov[cov["system_id"] == "b"].iloc[0]
    assert b["actual_polls"] == 800 and b["completeness_pct"] == pytest.approx(55.6)


def test_threshold_is_a_parameter():
    snaps = pd.concat([minutes("2026-03-01", 1440, "a"), minutes("2026-03-01", 1300, "b")])
    assert status_of(daily_coverage(snaps), "b") == ["partial"]  # 90.3 %
    assert status_of(daily_coverage(snaps, ok_threshold_pct=90), "b") == ["ok"]
    with pytest.raises(ValueError):
        daily_coverage(snaps, ok_threshold_pct=0)


def test_poll_resolution_and_expected_polls():
    snaps = minutes("2026-03-01", 96, "a", every=15)
    cov = daily_coverage(snaps, poll_resolution="15min")
    assert cov["expected_polls"].iloc[0] == 96 and cov["status"].iloc[0] == "ok"
    assert (
        daily_coverage(snaps, expected_polls=200, poll_resolution="15min")["status"].iloc[0] != "ok"
    )


def test_a_silent_system_while_the_collector_ran_is_an_operator_outage():
    # b polls on day 1 only; a keeps going for three days: b is silent on days 2 and 3.
    snaps = pd.concat([minutes("2026-03-01", 3 * 1440, "a"), minutes("2026-03-01", 1440, "b")])
    cov = daily_coverage(snaps)
    assert status_of(cov, "b") == ["ok", "outage_operator", "outage_operator"]
    silent = find_silent_feeds(cov)
    assert silent["system_id"].tolist() == ["b"] and silent["n_days"].iloc[0] == 2
    assert pd.isna(silent["end_utc"].iloc[0])  # ongoing: it reaches the last day


def test_a_silent_run_that_ends_has_an_end():
    both = pd.concat([minutes("2026-03-01", 1440, "b"), minutes("2026-03-03", 1440, "b")])
    snaps = pd.concat([minutes("2026-03-01", 3 * 1440, "a"), both])
    silent = find_silent_feeds(daily_coverage(snaps))
    assert silent["end_utc"].iloc[0] == pd.Timestamp("2026-03-03", tz="UTC")


def test_collector_gap_explains_the_day_for_every_system():
    parts = []
    for s in ("a", "b"):
        parts += [minutes("2026-03-01", 600, s), minutes("2026-03-01T16:00", 480 + 1440, s)]
    cov = daily_coverage(pd.concat(parts))
    assert status_of(cov, "a")[0] == "outage_collector" == status_of(cov, "b")[0]
    gaps = find_collector_gaps(pd.concat(parts))
    assert len(gaps) == 1 and gaps["duration"].iloc[0] == pd.Timedelta(hours=6)


def test_declared_incident_replaces_detection_of_the_same_stretch():
    snaps = pd.concat([minutes("2026-03-01", 600, "a"), minutes("2026-03-01T16:00", 480, "a")])
    known = add_incident(
        None, "move", "2026-03-01T10:00Z", "2026-03-01T16:00Z", cause="outage_collector"
    )
    assert find_collector_gaps(snaps, known=known).empty
    assert status_of(daily_coverage(snaps, known_incidents=known), "a") == ["outage_collector"]


def test_declared_operator_incident_is_scoped_to_its_system():
    snaps = pd.concat([minutes("2026-03-01", 700, "a"), minutes("2026-03-01", 700, "b")])
    known = add_incident(None, "x", "2026-03-01", "2026-03-02", cause="outage_operator", scope="a")
    cov = daily_coverage(snaps, known_incidents=known)
    assert status_of(cov, "a") == ["outage_operator"] and status_of(cov, "b") == ["partial"]


def test_end_leaves_out_the_day_in_progress():
    snaps = minutes("2026-03-01", 1440 + 100, "a")
    assert len(daily_coverage(snaps)) == 2
    assert len(daily_coverage(snaps, end="2026-03-01")) == 1


def test_both_zero_pct_and_units_reporting_median():
    t = pd.to_datetime(["2026-03-01T00:00Z"] * 4)
    df = pd.DataFrame(
        {
            "system_id": "a",
            "station_id": list("wxyz"),
            "fetched_at": t,
            "num_bikes_available": [0, 0, 3, pd.NA],
            "num_docks_available": [0, 5, 0, 0],
        }
    ).astype({"num_bikes_available": "Int64"})
    row = daily_coverage(df).iloc[0]
    assert row["both_zero_pct"] == 25.0 and row["units_reporting_median"] == 4.0


def test_empty_and_naive_inputs():
    assert daily_coverage(minutes("2026-03-01", 0, "a")).empty
    naive = minutes("2026-03-01", 1440, "a")
    naive["fetched_at"] = naive["fetched_at"].dt.tz_localize(None)
    assert daily_coverage(naive)["status"].tolist() == ["ok"]
    with pytest.raises(SchemaError):
        daily_coverage(pd.DataFrame({"fetched_at": []}))
    with pytest.raises(ValueError):
        daily_coverage(pd.DataFrame({"system_id": ["a"], "fetched_at": ["not a date"]}))


def test_detect_incidents_is_stable_and_keeps_known():
    snaps = pd.concat(
        [
            minutes("2026-03-01", 600, "a"),
            minutes("2026-03-01T16:00", 480 + 1440, "a"),
            minutes("2026-03-01", 600, "c"),
        ]
    )
    known = add_incident(None, "note", "2026-02-01", "2026-02-02", cause="ambiguous_missing_value")
    first = assess(snaps, known_incidents=known)
    again = assess(snaps, known_incidents=known)
    assert first.incidents["incident_id"].tolist() == again.incidents["incident_id"].tolist()
    ids = set(first.incidents["incident_id"])
    assert "note" in ids and any(i.startswith("collector-gap-") for i in ids)
    assert list(first.incidents.columns) == INCIDENT_COLUMNS
    assert first.summary()["system_days"] == len(first.coverage)
    assert detect_incidents(first.coverage).shape[1] == 6


def test_registry_validation():
    with pytest.raises(GBFSValidationError, match="unknown incident cause"):
        incident_registry([{"incident_id": "a", "start_utc": "2026-01-01", "cause": "oops"}])
    row = {"incident_id": "a", "start_utc": "2026-01-01", "cause": "outage_operator"}
    with pytest.raises(GBFSValidationError, match="duplicated"):
        incident_registry([row, row])
    with pytest.raises(GBFSValidationError, match="before they start"):
        incident_registry([{**row, "end_utc": "2025-12-01"}])
    with pytest.raises(SchemaError):
        incident_registry([{"incident_id": "a"}])
    assert incident_registry(None).empty


@pytest.mark.parametrize("suffix", [".json", ".csv"])
def test_registry_round_trip(tmp_path, suffix):
    reg = add_incident(
        None,
        "one",
        "2026-03-01T10:00Z",
        "2026-03-01T11:30Z",
        cause="outage_collector",
        summary='café, "quoted"',
    )
    reg = add_incident(reg, "two", "2026-03-05", cause="outage_operator", scope="a,b")
    path = write_incidents(reg, tmp_path / f"incidents{suffix}")
    back = read_incidents(path)
    assert back["incident_id"].tolist() == ["one", "two"]
    assert back["summary"].iloc[0] == 'café, "quoted"'
    assert pd.isna(back["end_utc"].iloc[1]) and back["scope"].iloc[1] == "a,b"
    with pytest.raises(ValueError):
        write_incidents(reg, tmp_path / "x.txt")


def test_incidents_overlapping_window_and_scope():
    reg = incident_registry(
        [
            {
                "incident_id": "all",
                "start_utc": "2026-03-05",
                "end_utc": "2026-03-06",
                "cause": "outage_collector",
            },
            {
                "incident_id": "a",
                "start_utc": "2026-03-05",
                "end_utc": "2026-03-06",
                "cause": "outage_operator",
                "scope": "a",
            },
            {
                "incident_id": "open",
                "start_utc": "2026-01-01",
                "cause": "outage_operator",
                "scope": "b",
            },
        ]
    )
    assert incidents_overlapping(reg, "2026-03-01", "2026-03-10")["incident_id"].tolist() == [
        "open",
        "a",
        "all",
    ]
    assert incidents_overlapping(reg, "2026-03-01", "2026-03-10", ["b"])[
        "incident_id"
    ].tolist() == ["open", "all"]
    assert incidents_overlapping(reg, "2026-04-01", "2026-04-02", ["a"]).empty


# --- indicators ------------------------------------------------------------------------


def status_rows(bikes, docks, capacity=10, system="a", when="2026-03-01T10:00Z", ids=None):
    n = len(bikes)
    return pd.DataFrame(
        {
            "system_id": system,
            "station_id": ids or [f"s{i}" for i in range(n)],
            "fetched_at": pd.to_datetime([when] * n),
            "num_bikes_available": pd.array(bikes, dtype="Int64"),
            "num_docks_available": pd.array(docks, dtype="Int64"),
            "capacity": capacity,
        }
    )


def test_both_zero_suspect_cases():
    df = status_rows([0, 0, 3, None], [0, 5, 0, 0], capacity=[10, 10, 10, 10])
    out = add_quality_indicators(df)
    assert out["both_zero_suspect"].tolist()[:3] == [True, False, False]
    assert pd.isna(out["both_zero_suspect"].iloc[3])
    no_cap = add_quality_indicators(status_rows([0, 2], [0, 3], capacity=[None, 10]))
    assert pd.isna(no_cap["both_zero_suspect"].iloc[0])
    zero_cap = add_quality_indicators(status_rows([0, 2], [0, 3], capacity=[0, 10]))
    assert zero_cap["both_zero_suspect"].tolist() == [False, False]


def test_capacity_can_come_from_a_separate_table():
    df = status_rows([0, 0, 2], [0, 0, 3]).drop(columns="capacity")
    cap = pd.DataFrame({"station_id": ["s0"], "capacity": [12]})
    out = add_quality_indicators(df, capacity=cap)
    assert out["both_zero_suspect"].iloc[0]
    assert out["both_zero_suspect"].iloc[1:].isna().all()  # no capacity known


def test_unsupported_field_is_named_and_masked_per_system_and_month():
    docks_zero = status_rows([3, 0, 5], [0, 0, 0])
    other = status_rows([3, 0, 5], [4, 0, 2], system="b")
    next_month = status_rows([3], [0], when="2026-04-01T10:00Z", ids=["s9"])
    df = pd.concat([docks_zero, other, next_month], ignore_index=True)
    unsupported = field_unsupported_by_operator(df)
    assert unsupported[["system_id", "field"]].values.tolist() == [
        ["a", "num_docks_available"],
        ["a", "num_docks_available"],
    ]
    out = add_quality_indicators(df)
    assert out.loc[out["system_id"] == "a", "num_docks_available"].isna().all()
    assert out.loc[out["system_id"] == "b", "num_docks_available"].notna().all()
    assert out["field_unsupported_by_operator"].iloc[0] == "num_docks_available"
    assert pd.isna(out["field_unsupported_by_operator"].iloc[3])
    # masked count: the pair-based indicator cannot decide
    assert out.loc[out["system_id"] == "a", "both_zero_suspect"].isna().all()
    kept = add_quality_indicators(df, mask_unsupported=False)
    assert kept.loc[kept["system_id"] == "a", "num_docks_available"].eq(0).all()
    assert df["num_docks_available"].eq(0).sum() == 5  # input untouched


def test_period_all_and_day():
    a = status_rows([1, 2], [0, 0], when="2026-03-01T10:00Z")
    b = status_rows([1, 2], [3, 0], when="2026-03-02T10:00Z", ids=["s0", "s1"])
    df = pd.concat([a, b], ignore_index=True)
    assert len(field_unsupported_by_operator(df, period="D")) == 1
    assert field_unsupported_by_operator(df, period="all").empty
    with pytest.raises(ValueError):
        field_unsupported_by_operator(df, period="W")


def test_network_all_zero_anomaly_per_poll():
    quiet = status_rows([0] * 20, [0] * 20, when="2026-03-01T10:00Z")
    normal = status_rows([0] + [4] * 19, [0] + [3] * 19, when="2026-03-01T10:01Z")
    only_bikes_zero = status_rows([0] * 20, [2] * 20, when="2026-03-01T10:02Z")
    out = add_quality_indicators(pd.concat([quiet, normal, only_bikes_zero], ignore_index=True))
    flag = out["network_all_zero_anomaly"]
    assert flag.iloc[:20].all() and not flag.iloc[20:].any()


def test_network_all_zero_ignores_the_unpublished_field():
    # A dockless-style system: docks are always 0 (unpublished). Zero bikes everywhere is the anomaly.
    quiet = status_rows([0] * 10, [0] * 10, when="2026-03-01T10:00Z")
    normal = status_rows([3] * 10, [0] * 10, when="2026-03-01T10:01Z")
    out = add_quality_indicators(pd.concat([quiet, normal], ignore_index=True))
    assert out["network_all_zero_anomaly"].tolist() == [True] * 10 + [False] * 10


def test_indicators_flag_and_never_drop_rows():
    df = status_rows([0] * 5, [0] * 5)
    out = add_quality_indicators(df)
    assert len(out) == len(df) and list(out.index) == list(df.index)
    assert {
        "field_unsupported_by_operator",
        "both_zero_suspect",
        "network_all_zero_anomaly",
    } <= set(out.columns)


@settings(max_examples=40, deadline=None)
@given(
    n=st.integers(min_value=1, max_value=60),
    seed=st.integers(min_value=0, max_value=10_000),
    threshold=st.floats(min_value=1, max_value=100),
)
def test_property_completeness_is_bounded_and_status_agrees_with_threshold(n, seed, threshold):
    import numpy as np

    rng = np.random.default_rng(seed)
    offsets = np.sort(rng.choice(1440, size=n, replace=False))
    t = pd.Timestamp("2026-03-01", tz="UTC") + pd.to_timedelta(offsets, unit="min")
    snaps = pd.DataFrame({"system_id": "a", "fetched_at": t})
    cov = daily_coverage(snaps, ok_threshold_pct=threshold)
    row = cov.iloc[0]
    assert row["actual_polls"] == n and 0 < row["completeness_pct"] <= 100
    assert (row["status"] == "ok") == (row["completeness_pct"] >= threshold)

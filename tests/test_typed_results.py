"""Typed results: declared columns and logical dtypes, `AuditReport` and `QualityReport`."""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

import gbfs_toolkit as gb
from gbfs_toolkit import quality
from gbfs_toolkit.aggregate import AGGREGATE_COLUMNS, AGGREGATE_DTYPES, aggregate_availability
from gbfs_toolkit.audit.static import AUDIT_REPORT_COLUMNS, AUDIT_REPORT_DTYPES, AuditReport
from gbfs_toolkit.stations.match import MATCH_COLUMNS, MATCH_DTYPES, match_stations


def has_kind(series: pd.Series, kind: str) -> bool:
    """Whether ``series`` has the logical type ``kind`` (the pandas dtype of text varies)."""
    dtype = series.dtype
    if kind == "string":
        return pd.api.types.is_string_dtype(dtype) or dtype == "object"
    if kind == "date":
        return dtype == "object" and all(isinstance(v, dt.date) for v in series.dropna())
    if kind == "datetime64[UTC]":
        return isinstance(dtype, pd.DatetimeTZDtype) and str(dtype.tz) == "UTC"
    if kind == "datetime64[naive]":
        return pd.api.types.is_datetime64_dtype(dtype)
    if kind == "bool":
        return pd.api.types.is_bool_dtype(dtype)
    return str(dtype) == kind


def assert_schema(frame: pd.DataFrame, columns: list[str], dtypes: dict[str, str]) -> None:
    assert list(frame.columns) == [c for c in columns if c in frame.columns]
    for column in frame.columns:
        assert has_kind(frame[column], dtypes[column]), (column, frame[column].dtype)


def snapshots() -> pd.DataFrame:
    t = pd.date_range("2026-03-01T08:00Z", periods=90, freq="min")
    return pd.DataFrame(
        {
            "system_id": "a",
            "station_id": "s",
            "fetched_at": t,
            "num_bikes_available": np.arange(90) % 7,
            "num_docks_available": 7 - np.arange(90) % 7,
            "is_renting": True,
            "capacity": 7,
        }
    )


def test_aggregate_declares_its_columns_and_types():
    assert set(AGGREGATE_DTYPES) == set(AGGREGATE_COLUMNS)
    with_zone = aggregate_availability(snapshots(), "15min", tz="Europe/Paris")
    assert_schema(with_zone, AGGREGATE_COLUMNS, AGGREGATE_DTYPES)
    assert_schema(aggregate_availability(snapshots(), "1h"), AGGREGATE_COLUMNS, AGGREGATE_DTYPES)
    pytest.importorskip("duckdb")
    got = aggregate_availability(snapshots(), "15min", tz="Europe/Paris", engine="duckdb")
    assert_schema(got, AGGREGATE_COLUMNS, AGGREGATE_DTYPES)


def test_quality_tables_declare_their_columns_and_types():
    assert set(quality.COVERAGE_DTYPES) == set(quality.COVERAGE_COLUMNS)
    assert set(quality.INCIDENT_DTYPES) == set(quality.INCIDENT_COLUMNS)
    report = quality.assess(snapshots())
    assert_schema(report.coverage, quality.COVERAGE_COLUMNS, quality.COVERAGE_DTYPES)
    assert_schema(report.incidents, quality.INCIDENT_COLUMNS, quality.INCIDENT_DTYPES)
    assert_schema(quality.incident_registry(), quality.INCIDENT_COLUMNS, quality.INCIDENT_DTYPES)
    empty = quality.daily_coverage(snapshots().iloc[:0])
    assert list(empty.columns) == quality.COVERAGE_COLUMNS


def test_match_declares_its_columns_and_types():
    stations = pd.DataFrame(
        {"station_id": ["1", "2"], "name": ["A", "B"], "lat": [48.1, 48.2], "lon": [2.1, 2.2]}
    )
    out = match_stations(stations, stations)
    assert set(MATCH_DTYPES) == set(MATCH_COLUMNS)
    assert_schema(out, MATCH_COLUMNS, MATCH_DTYPES)


def test_quality_report_reads_like_the_pair_of_frames_it_holds():
    report = quality.assess(snapshots())
    assert report["coverage"] is report.coverage and report["incidents"] is report.incidents
    assert list(report.keys()) == ["coverage", "incidents"]
    frames = report.to_frames()
    assert set(frames) == {"coverage", "incidents"} and frames["coverage"] is report.coverage
    assert report.to_frame() is report.coverage
    with pytest.raises(KeyError, match="coverage"):
        report["nothing"]
    assert report.summary()["system_days"] == 1


def audit_fixture() -> pd.DataFrame:
    rng = np.random.default_rng(0)
    rows = []
    for sid, n in (("p", 25), ("q", 25)):
        rows.append(
            pd.DataFrame(
                {
                    "system_id": sid,
                    "station_id": [f"{sid}{i}" for i in range(n)],
                    "station_type": "docked_bike",
                    "capacity": 15.0 if sid == "p" else rng.integers(10, 35, n).astype(float),
                    "lat": 48.85 + rng.normal(0, 0.02, n),
                    "lon": 2.35 + rng.normal(0, 0.03, n),
                }
            )
        )
    return pd.concat(rows, ignore_index=True)


def test_audit_report_is_a_dataframe_with_a_contract():
    report = gb.audit_static(audit_fixture())
    assert isinstance(report, AuditReport) and isinstance(report, pd.DataFrame)
    assert gb.AuditReport is AuditReport
    assert list(report.columns) == AUDIT_REPORT_COLUMNS
    assert set(AUDIT_REPORT_DTYPES) == set(AUDIT_REPORT_COLUMNS) - {"system_id", "station_id"}
    for column, kind in AUDIT_REPORT_DTYPES.items():
        assert has_kind(report[column], kind), column
    # the current usage: access by key, selection, grouping
    assert report["A2"].dtype == bool and report.loc[report["A2"], "station_id"].shape[0] == 25
    assert report.groupby("system_id")["flagged"].sum().to_dict() == {"p": 25, "q": 0}
    # readers
    assert report.n_flagged == 25
    assert report.flag_counts.to_dict() == {f: int(report[f].sum()) for f in gb.AUDIT_FLAGS}
    assert list(report.rule_flags.columns) == list(gb.AUDIT_FLAGS)
    assert len(report.flagged_stations()) == 25
    by_system = report.by_system()
    assert by_system.loc["p", ["n_stations", "n_flagged", "A2"]].tolist() == [25, 25, 25]
    # conversion to a plain DataFrame, and derived frames are plain DataFrames
    plain = report.to_frame()
    assert type(plain) is pd.DataFrame and plain.equals(pd.DataFrame(report))
    assert type(report[["A1", "A2"]]) is pd.DataFrame and type(report.head()) is pd.DataFrame
    pd.testing.assert_frame_equal(report, gb.audit_static(audit_fixture()))

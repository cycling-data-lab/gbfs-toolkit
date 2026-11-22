"""history: content versions only when the content changes; and Collector.poll_metadata."""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from gbfs_toolkit.history import (
    content_fingerprint,
    list_versions,
    read_version,
    record_version,
)


def meta(*, rules='{"a": 1, "b": 2}', name="Demo", when="2026-01-05T10:00Z", extra=None):
    df = pd.DataFrame(
        {
            "vehicle_type_id": ["bike", "ebike"],
            "name": [name, "E"],
            "rules": [rules, "[1, 2]"],
            "range": [None, 80.0],
            "fetched_at": pd.to_datetime([when] * 2),
        }
    )
    return df if extra is None else df.assign(**extra)


def test_fingerprint_ignores_fetch_time_row_order_column_order_key_order_and_int_float():
    base = meta()
    shuffled = meta(rules='{"b": 2, "a": 1}', when="2030-01-01T00:00Z").iloc[::-1]
    shuffled = shuffled[list(reversed(shuffled.columns))]
    shuffled["range"] = shuffled["range"].replace(80.0, 80)  # same value, other spelling
    assert content_fingerprint(base) == content_fingerprint(shuffled)


def test_fingerprint_sees_real_changes():
    base = content_fingerprint(meta())
    assert content_fingerprint(meta(name="Renamed")) != base
    assert content_fingerprint(meta(rules='{"a": 1, "b": 3}')) != base
    assert content_fingerprint(meta(rules='{"a": 1}')) != base
    assert content_fingerprint(meta().iloc[:1]) != base
    # the order inside a JSON array is content
    swapped = meta()
    swapped["rules"] = ['{"a": 1, "b": 2}', "[2, 1]"]
    assert content_fingerprint(swapped) != base


def test_absent_column_equals_empty_column_and_ignore_is_configurable():
    with_empty = meta().assign(note=[None, None])
    assert content_fingerprint(with_empty) == content_fingerprint(meta())
    assert content_fingerprint(meta(), ignore=()) != content_fingerprint(
        meta(when="2026-02-01T00:00Z"), ignore=()
    )
    nested = pd.DataFrame({"d": [{"x": 1, "y": None}]})
    assert content_fingerprint(nested) == content_fingerprint(pd.DataFrame({"d": [{"x": 1}]}))


def test_empty_frame_and_numpy_values():
    assert content_fingerprint(pd.DataFrame({"a": []})) == content_fingerprint(
        pd.DataFrame({"b": []})
    )
    a = pd.DataFrame({"n": np.array([1, 2], dtype="int64"), "f": np.array([0.5, 1.0])})
    b = pd.DataFrame({"n": [1.0, 2.0], "f": [0.5, 1]})
    assert content_fingerprint(a) == content_fingerprint(b)


TODAY = dt.date(2026, 3, 1)


def test_new_content_is_written_unchanged_content_is_not(tmp_path):
    first = record_version(meta(), tmp_path, today=TODAY)
    assert first.action == "written" and first.path.name == "2026-01-05.parquet"
    same = record_version(meta(when="2026-02-10T10:00Z"), tmp_path, today=TODAY)
    assert same.action == "unchanged" and same.path == first.path
    changed = record_version(meta(name="Renamed", when="2026-02-10T10:00Z"), tmp_path, today=TODAY)
    assert changed.action == "written" and changed.path.name == "2026-02-10.parquet"
    assert list_versions(tmp_path)["version_date"].tolist() == [
        dt.date(2026, 1, 5),
        dt.date(2026, 2, 10),
    ]


def test_a_closed_day_is_never_rewritten_but_today_is(tmp_path):
    record_version(meta(), tmp_path, today=TODAY)
    renamed = meta(name="V2", when="2026-01-05T18:00Z")  # same closed day, different content
    r = record_version(renamed, tmp_path, today=TODAY)
    assert r.action == "kept_closed_day"
    assert read_version(tmp_path)["name"].iloc[0] == "Demo"
    # on the current day a second fetch replaces the first
    record_version(meta(name="A", when="2026-03-01T08:00Z"), tmp_path, today=TODAY)
    again = record_version(meta(name="B", when="2026-03-01T20:00Z"), tmp_path, today=TODAY)
    assert again.action == "written" and read_version(tmp_path)["name"].iloc[0] == "B"
    assert len(list_versions(tmp_path)) == 2


def test_a_fetch_older_than_the_latest_version_is_ignored(tmp_path):
    record_version(meta(name="New", when="2026-02-01T00:00Z"), tmp_path, today=TODAY)
    r = record_version(meta(name="Old", when="2026-01-01T00:00Z"), tmp_path, today=TODAY)
    assert r.action == "older_than_latest" and len(list_versions(tmp_path)) == 1


def test_dry_run_writes_nothing_and_errors_are_clear(tmp_path):
    r = record_version(meta(), tmp_path / "h", dry_run=True, today=TODAY)
    assert r.action == "written" and not (tmp_path / "h").exists()
    with pytest.raises(ValueError, match="no usable time"):
        record_version(meta().assign(fetched_at=pd.NaT), tmp_path)
    from gbfs_toolkit.core.models import SchemaError

    with pytest.raises(SchemaError):
        record_version(meta().drop(columns="fetched_at"), tmp_path)


def test_read_version_by_day_and_as_of(tmp_path):
    record_version(meta(name="V1", when="2026-01-05T00:00Z"), tmp_path, today=TODAY)
    record_version(meta(name="V2", when="2026-02-10T00:00Z"), tmp_path, today=TODAY)
    (tmp_path / "notes.parquet").write_bytes(b"x")  # not a dated version: ignored
    assert read_version(tmp_path, "2026-01-05")["name"].iloc[0] == "V1"
    assert read_version(tmp_path, dt.date(2026, 2, 1), asof=True)["name"].iloc[0] == "V1"
    assert read_version(tmp_path, "2026-03-01", asof=True)["name"].iloc[0] == "V2"
    with pytest.raises(FileNotFoundError):
        read_version(tmp_path, "2026-02-01")
    with pytest.raises(FileNotFoundError):
        read_version(tmp_path, "2025-01-01", asof=True)
    with pytest.raises(FileNotFoundError):
        read_version(tmp_path / "empty")


@settings(max_examples=40, deadline=None)
@given(
    rows=st.lists(st.tuples(st.text(max_size=5), st.integers(-5, 5)), min_size=0, max_size=8),
    seed=st.integers(0, 99),
)
def test_property_fingerprint_does_not_depend_on_row_order(rows, seed):
    df = pd.DataFrame(rows, columns=["k", "v"])
    shuffled = df.sample(frac=1, random_state=seed)
    assert content_fingerprint(df) == content_fingerprint(shuffled)


# --- Collector.poll_metadata -----------------------------------------------------------------


def test_collector_keeps_metadata_versions_only_on_change(tmp_path):
    from gbfs_toolkit.collect import Collector

    docs = {
        "https://x/gbfs.json": {
            "version": "2.3",
            "data": {
                "en": {
                    "feeds": [
                        {"name": "system_information", "url": "https://x/si.json"},
                        {"name": "vehicle_types", "url": "https://x/vt.json"},
                    ]
                }
            },
        },
        "https://x/si.json": {
            "data": {"system_id": "demo", "name": "Demo", "timezone": "Europe/Paris"}
        },
        "https://x/vt.json": {
            "data": {
                "vehicle_types": [
                    {"vehicle_type_id": "b", "form_factor": "bicycle", "propulsion_type": "human"}
                ]
            }
        },
    }
    clock = iter(
        pd.to_datetime(
            [
                "2026-01-05T10:00Z",
                "2026-01-05T10:00Z",
                "2026-01-06T10:00Z",
                "2026-01-06T10:00Z",
                "2026-01-07T10:00Z",
                "2026-01-07T10:00Z",
            ]
        )
    )
    c = Collector(
        {"s": "https://x/gbfs.json"},
        tmp_path,
        user_agent="ua",
        get_json=docs.__getitem__,
        now=lambda: next(clock),
    )
    first = c.poll_metadata(feeds=("system_information", "vehicle_types", "system_regions"))
    assert first.set_index("feed")["outcome"].to_dict() == {
        "system_information": "written",
        "vehicle_types": "written",
        "system_regions": "unavailable",
    }
    second = c.poll_metadata(feeds=("system_information", "vehicle_types"))
    assert set(second["outcome"]) == {"unchanged"}
    docs["https://x/vt.json"]["data"]["vehicle_types"][0]["propulsion_type"] = "electric_assist"
    third = c.poll_metadata(feeds=("system_information", "vehicle_types"))
    assert third.set_index("feed")["outcome"].to_dict() == {
        "system_information": "unchanged",
        "vehicle_types": "written",
    }
    assert len(list_versions(tmp_path / "metadata" / "s" / "vehicle_types")) == 2
    with pytest.raises(ValueError):
        c.poll_metadata(feeds=("alerts",))

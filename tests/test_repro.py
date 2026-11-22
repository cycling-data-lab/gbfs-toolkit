"""repro: fingerprint, manifest, verification, materialisation and CI samples."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from gbfs_toolkit.core.errors import GBFSValidationError
from gbfs_toolkit.repro import (
    MANIFEST_FILE,
    create_manifest,
    export_sample,
    fingerprint,
    materialize,
    read_manifest,
    verify_manifest,
    write_manifest,
)


def table(n=6, system="a"):
    return pd.DataFrame(
        {
            "system_id": system,
            "station_id": [f"s{i % 3}" for i in range(n)],
            "observed_at_utc": pd.date_range("2026-03-01T00:00Z", periods=n, freq="7min"),
            "num_bikes_available": pd.array(
                [i if i % 4 else None for i in range(n)], dtype="Int64"
            ),
            "is_renting": pd.array([True, None] * (n // 2), dtype="boolean"),
            "lat": np.linspace(43.5, 43.6, n),
            "name": [None if i == 2 else f"Station {i}" for i in range(n)],
        }
    )


def test_fingerprint_ignores_row_order_column_order_and_int_vs_float_spelling():
    df = table()
    other = df.iloc[::-1].reset_index(drop=True)[list(reversed(df.columns))]
    other["num_bikes_available"] = other["num_bikes_available"].astype("Float64")
    assert fingerprint(df) == fingerprint(other)


def test_fingerprint_sees_content_changes():
    df = table()
    base = fingerprint(df)
    for change in (
        df.assign(name=df["name"].fillna("x")),
        df.iloc[:-1],
        df.assign(lat=df["lat"] + 1e-6),
        df.assign(station_id=df["station_id"].str.upper()),
        df.assign(is_renting=pd.array([True, False] * 3, dtype="boolean")),
        df.assign(observed_at_utc=df["observed_at_utc"] + pd.Timedelta(seconds=1)),
        df.rename(columns={"lat": "latitude"}),
    ):
        assert fingerprint(change) != base


def test_the_12_digit_convention_is_documented_behaviour():
    df = pd.DataFrame({"x": [0.1 + 0.2]})
    assert fingerprint(df) == fingerprint(pd.DataFrame({"x": [0.3]}))  # noise at the 17th digit
    assert fingerprint(df) != fingerprint(pd.DataFrame({"x": [0.3001]}))


def test_exclude_and_empty_inputs():
    df = table()
    assert fingerprint(df, exclude=["name"]) == fingerprint(df.drop(columns="name"))
    assert fingerprint(df.iloc[0:0]) != fingerprint(pd.DataFrame({"zzz": []}))  # schema counts
    assert fingerprint(df.iloc[0:0]) == fingerprint(df.iloc[0:0].copy())
    assert fingerprint(df, exclude=list(df.columns)) == fingerprint(pd.DataFrame())


def test_naive_aware_and_date_times_agree_when_they_denote_the_same_instant():
    aware = pd.DataFrame({"t": pd.to_datetime(["2026-03-01T10:00Z"])})
    naive = pd.DataFrame({"t": pd.to_datetime(["2026-03-01T10:00"])})
    local = pd.DataFrame({"t": pd.to_datetime(["2026-03-01T11:00"]).tz_localize("Europe/Paris")})
    assert fingerprint(aware) == fingerprint(naive) == fingerprint(local)
    dates = pd.DataFrame({"d": [pd.Timestamp("2026-03-01").date()]})
    midnight = pd.DataFrame({"d": pd.to_datetime(["2026-03-01"])})
    assert fingerprint(dates) == fingerprint(midnight)


def test_fingerprint_agrees_across_parquet_and_memory(tmp_path):
    pytest.importorskip("pyarrow")
    df = table()
    df.to_parquet(tmp_path / "t.parquet", index=False)
    assert fingerprint(tmp_path / "t.parquet") == fingerprint(df)
    assert fingerprint(str(tmp_path / "t.parquet")) == fingerprint(df)


def test_fingerprint_matches_the_duckdb_expression(tmp_path):
    """The same table fingerprinted in SQL and here gives the same value."""
    duckdb = pytest.importorskip("duckdb")
    df = table(12).assign(extra=["é,|x"] * 12)
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    con.register("t", df)
    types = {r[0]: r[1] for r in con.execute("DESCRIBE SELECT * FROM t").fetchall()}
    exprs = []
    for name in sorted(types):
        c = f'"{name}"'
        k = types[name].upper()
        if k.startswith(("TIMESTAMP", "DATE")):
            e = f"CAST(epoch_us(CAST({c} AS TIMESTAMPTZ)) AS VARCHAR)"
        elif k == "BOOLEAN" or k.startswith(
            ("TINYINT", "SMALLINT", "INTEGER", "BIGINT", "FLOAT", "DOUBLE")
        ):
            e = f"printf('%.12g', CASE WHEN isnan(CAST({c} AS DOUBLE)) THEN NULL ELSE CAST({c} AS DOUBLE) END)"
        else:
            e = f"CAST({c} AS VARCHAR)"
        exprs.append(f"coalesce({e}, '∅')")
    header = "|".join(sorted(types)) + "\n"
    sql = (
        f"SELECT sha256('{header}' || coalesce(string_agg(h, '' ORDER BY h), '')) FROM "
        f"(SELECT md5(concat_ws('|', {', '.join(exprs)})) AS h FROM t)"
    )
    assert "sha256:" + con.execute(sql).fetchone()[0] == fingerprint(df)


def test_manifest_round_trip_and_validation(tmp_path):
    df = table()
    m = create_manifest(
        df,
        table="stations",
        systems=["a"],
        start="2026-03-01",
        end=pd.Timestamp("2026-03-31T10:00Z"),
        columns=["station_id"],
        source="release-2026-03",
    )
    assert (m["rows"], m["start_utc"], m["end_utc"], m["systems"]) == (
        6,
        "2026-03-01",
        "2026-03-31",
        ["a"],
    )
    path = write_manifest(m, tmp_path / "m" / MANIFEST_FILE)
    assert read_manifest(path) == m
    assert not list(tmp_path.rglob("*.tmp"))
    assert "/home" not in json.dumps(m) and "user" not in json.dumps(m).lower()
    (tmp_path / "bad.json").write_text("{not json")
    with pytest.raises(GBFSValidationError, match="not a JSON"):
        read_manifest(tmp_path / "bad.json")
    (tmp_path / "other.json").write_text('{"format": "something/9", "table": "t"}')
    with pytest.raises(GBFSValidationError, match="not a gbfs-toolkit-data-manifest/1"):
        read_manifest(tmp_path / "other.json")


def test_verify_reports_rows_and_fingerprint():
    df = table()
    m = create_manifest(df, table="t")
    assert verify_manifest(m, df.sample(frac=1, random_state=1)) == {
        "rows": True,
        "fingerprint": True,
    }
    with pytest.raises(GBFSValidationError, match="5 rows instead of 6"):
        verify_manifest(m, df.iloc[:-1])
    changed = df.assign(lat=df["lat"] + 1)
    assert verify_manifest(m, changed, strict=False) == {"rows": True, "fingerprint": False}
    with pytest.raises(GBFSValidationError, match="fingerprint"):
        verify_manifest(m, changed)


def lake(tmp_path):
    pytest.importorskip("pyarrow")
    from gbfs_toolkit.store import write_lake

    root = tmp_path / "lake"
    df = pd.concat([table(40, "a"), table(40, "b")], ignore_index=True)
    write_lake(df, root)
    return root, df


def test_materialize_selects_verifies_and_caches(tmp_path):
    root, df = lake(tmp_path)
    selected = df[df["system_id"] == "a"]
    m = create_manifest(
        selected, table="stations", systems=["a"], start="2026-03-01", end="2026-03-01"
    )
    cache = tmp_path / "cache"
    path = materialize(m, root, cache_dir=cache)
    assert path.suffix == ".parquet" and (cache / ".gitignore").read_text().rstrip().endswith("*")
    assert fingerprint(path) == m["fingerprint"]
    # second call: served from the cache even if the lake is gone
    import shutil

    shutil.rmtree(root)
    frame = materialize(m, root, cache_dir=cache, load=True)
    assert len(frame) == len(selected)


def test_materialize_refuses_data_that_differ_and_keeps_nothing(tmp_path):
    root, df = lake(tmp_path)
    m = create_manifest(
        df[df["system_id"] == "a"],
        table="stations",
        systems=["a"],
        start="2026-03-01",
        end="2026-03-01",
    )
    m["fingerprint"] = "sha256:" + "0" * 64
    with pytest.raises(GBFSValidationError, match="differ from the manifest"):
        materialize(m, root, cache_dir=tmp_path / "cache")
    assert not list((tmp_path / "cache").glob("*.parquet"))
    assert materialize(m, root, cache_dir=tmp_path / "cache", verify=False).exists()
    with pytest.raises(ValueError):
        materialize(m, cache_dir=tmp_path / "c2")


def test_materialize_with_a_custom_reader_and_a_manifest_file(tmp_path):
    pytest.importorskip("pyarrow")
    df = table()
    m = create_manifest(df, table="t")
    mp = write_manifest(m, tmp_path / "m.json")
    out = materialize(mp, cache_dir=tmp_path / "c", reader=lambda manifest: df, load=True)
    assert len(out) == 6


def test_export_sample_is_small_readable_and_fingerprinted(tmp_path):
    pytest.importorskip("pyarrow")
    from gbfs_toolkit.store import read_lake

    df = pd.concat(
        [table(300, "a").assign(station_id=lambda d: "st" + (np.arange(len(d)) % 40).astype(str))],
        ignore_index=True,
    )
    m = export_sample(df, tmp_path / "sample", table="station_status", stations=5)
    assert (
        m["sample"]
        and len(m["stations"]) == 5
        and m["stations"] == sorted(df["station_id"].unique())[:5]
    )
    got = read_lake(tmp_path / "sample" / "data" / "station_status")
    assert set(got["station_id"]) == set(m["stations"]) and len(got) == m["rows"]
    assert verify_manifest(read_manifest(tmp_path / "sample" / MANIFEST_FILE), got) == {
        "rows": True,
        "fingerprint": True,
    }
    tiny = export_sample(df, tmp_path / "tiny", table="station_status", stations=20, max_bytes=1)
    assert len(tiny["stations"]) == 1  # halved until it fits or one station is left
    with pytest.raises(GBFSValidationError):
        export_sample(df.iloc[0:0], tmp_path / "e", table="t")
    with pytest.raises(GBFSValidationError):
        export_sample(df.drop(columns="station_id"), tmp_path / "f", table="t")
    # the sample is read by materialize like the real lake
    mm = create_manifest(got, table="station_status")
    assert len(
        materialize(
            mm,
            tmp_path / "sample" / "data" / "station_status",
            cache_dir=tmp_path / "cc",
            load=True,
        )
    ) == len(got)


@settings(max_examples=40, deadline=None)
@given(
    rows=st.lists(
        st.tuples(
            st.text(max_size=6), st.integers(-(10**6), 10**6), st.floats(-1e6, 1e6, allow_nan=False)
        ),
        max_size=15,
    ),
    seed=st.integers(0, 999),
)
def test_property_row_permutations_do_not_change_the_fingerprint(rows, seed):
    df = pd.DataFrame(rows, columns=["a", "b", "c"])
    assert fingerprint(df) == fingerprint(df.sample(frac=1, random_state=seed))


@settings(max_examples=30, deadline=None)
@given(values=st.lists(st.integers(0, 10**6), min_size=1, max_size=15), pos=st.integers(0, 14))
def test_property_changing_one_value_changes_the_fingerprint(values, pos):
    df = pd.DataFrame({"v": values})
    changed = df.copy()
    changed.loc[pos % len(df), "v"] += 1
    assert fingerprint(df) != fingerprint(changed)

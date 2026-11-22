"""Property-based tests of the computing functions: aggregates, quality, fingerprints, matches,
the lake round trip and the frozen release (needs hypothesis, a dev dependency)."""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("hypothesis")

from hypothesis import given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from gbfs_toolkit import quality  # noqa: E402
from gbfs_toolkit.aggregate import aggregate_availability, aggregate_levels  # noqa: E402
from gbfs_toolkit.repro import fingerprint  # noqa: E402
from gbfs_toolkit.stations.match import METHODS, match_stations  # noqa: E402

BASE = pd.Timestamp("2026-03-01", tz="UTC")


@st.composite
def snapshots(draw, max_rows: int = 80):
    """Polls of a few stations, distinct instants per station, counts sometimes missing."""
    n_stations = draw(st.integers(1, 3))
    rows = []
    for k in range(n_stations):
        offsets = draw(
            st.lists(
                st.integers(0, 3 * 24 * 3600),
                min_size=1,
                max_size=max_rows // n_stations,
                unique=True,
            )
        )
        for o in offsets:
            bikes = draw(st.one_of(st.none(), st.integers(0, 20)))
            docks = draw(st.one_of(st.none(), st.integers(0, 20)))
            rows.append(
                {
                    "system_id": "a" if k < 2 else "b",
                    "station_id": f"s{k}",
                    "fetched_at": BASE + pd.Timedelta(seconds=o),
                    "num_bikes_available": np.nan if bikes is None else float(bikes),
                    "num_docks_available": np.nan if docks is None else float(docks),
                }
            )
    return pd.DataFrame(rows)


def same(a: pd.DataFrame, b: pd.DataFrame) -> None:
    pd.testing.assert_frame_equal(a, b, check_exact=False, rtol=1e-9, atol=1e-9)


# ----------------------------------------------------------------------------- aggregates


@settings(max_examples=40, deadline=None)
@given(df=snapshots(), seed=st.integers(0, 999), freq=st.sampled_from(["15min", "1h", "1D"]))
def test_aggregate_does_not_depend_on_row_order(df, seed, freq):
    shuffled = df.sample(frac=1.0, random_state=seed).reset_index(drop=True)
    same(aggregate_availability(df, freq), aggregate_availability(shuffled, freq))


@settings(max_examples=40, deadline=None)
@given(df=snapshots())
def test_aggregate_bounds_and_conservation_hold_at_every_level(df):
    levels = aggregate_levels(df)  # raises if a level does not conserve n_obs
    for agg in levels.values():
        assert (agg["n_valid"] <= agg["n_obs"]).all()
        valid = agg[agg["n_valid"] > 0]
        assert (valid["bikes_min"] <= valid["bikes_mean"] + 1e-9).all()
        assert (valid["bikes_mean"] <= valid["bikes_max"] + 1e-9).all()
        for c in ("pct_empty", "pct_full"):
            v = agg[c].dropna()
            assert ((v >= 0) & (v <= 100)).all()
    # a pair of consecutive rows is attributed to one bucket whatever the width, so the total
    # volume of movement is the same at every level (up to the rounding of each bucket)
    exact = [aggregate_availability(df, f) for f in ("15min", "1h", "1D")]
    fine = pd.to_numeric(exact[0]["movement_volume"], errors="coerce").fillna(0).sum()
    coarse = pd.to_numeric(exact[2]["movement_volume"], errors="coerce").fillna(0).sum()
    assert abs(fine - coarse) <= len(exact[0])  # each bucket rounds to a whole bike at most once


@settings(max_examples=25, deadline=None)
@given(df=snapshots(), window=st.sampled_from(["15min", "1h", "5h", "1D"]))
def test_chunked_computation_equals_in_memory(df, window):
    pa = pytest.importorskip("pyarrow")
    table = pa.Table.from_pandas(df, preserve_index=False)
    reference = aggregate_availability(df, "1h")
    same(reference, aggregate_availability(table, "1h", engine="pandas", chunk=window))


@settings(max_examples=25, deadline=None)
@given(df=snapshots())
def test_duckdb_equals_pandas(df):
    pytest.importorskip("duckdb")
    same(aggregate_availability(df, "15min"), aggregate_availability(df, "15min", engine="duckdb"))


# ----------------------------------------------------------------------------- quality


@settings(max_examples=40, deadline=None)
@given(df=snapshots(), seed=st.integers(0, 999))
def test_coverage_is_bounded_ordered_and_independent_of_row_order(df, seed):
    cov = quality.daily_coverage(df)
    assert set(cov["status"]) <= set(quality.STATUSES)
    assert ((cov["completeness_pct"] >= 0) & (cov["completeness_pct"] <= 100)).all()
    assert (cov["actual_polls"] >= 0).all()
    assert (cov["expected_polls"] == 1440).all()
    for _, sub in cov.groupby("system_id"):  # days are consecutive within a system
        days = list(sub["date_utc"])
        assert days == [days[0] + dt.timedelta(days=i) for i in range(len(days))]
    shuffled = df.sample(frac=1.0, random_state=seed).reset_index(drop=True)
    pd.testing.assert_frame_equal(cov, quality.daily_coverage(shuffled))


@settings(max_examples=25, deadline=None)
@given(df=snapshots())
def test_a_system_keeps_its_polls_whatever_the_others_do(df):
    both = quality.daily_coverage(df)
    only_a = quality.daily_coverage(df[df["system_id"] == "a"])
    polls = lambda c, s: c[c["system_id"] == s].set_index("date_utc")["actual_polls"]  # noqa: E731
    shared = polls(only_a, "a").index.intersection(polls(both, "a").index)
    assert (polls(both, "a")[shared] == polls(only_a, "a")[shared]).all()


@settings(max_examples=25, deadline=None)
@given(df=snapshots())
def test_quality_engines_agree(df):
    pa = pytest.importorskip("pyarrow")
    pytest.importorskip("duckdb")
    table = pa.Table.from_pandas(df, preserve_index=False)
    reference = quality.daily_coverage(df)
    pd.testing.assert_frame_equal(reference, quality.daily_coverage(table, engine="duckdb"))
    pd.testing.assert_frame_equal(reference, quality.daily_coverage(table, engine="pandas"))
    pd.testing.assert_frame_equal(
        quality.find_collector_gaps(df), quality.find_collector_gaps(table, engine="duckdb")
    )


# ----------------------------------------------------------------------------- fingerprints


frames = st.lists(
    st.tuples(st.integers(-5, 5), st.floats(-5, 5, allow_nan=False), st.text(max_size=3)),
    min_size=0,
    max_size=10,
).map(lambda rows: pd.DataFrame(rows, columns=["a", "b", "c"]))


@settings(max_examples=50, deadline=None)
@given(df=frames, seed=st.integers(0, 99))
def test_fingerprint_ignores_row_and_column_order(df, seed):
    shuffled = df.sample(frac=1.0, random_state=seed)
    assert fingerprint(df) == fingerprint(shuffled)
    assert fingerprint(df) == fingerprint(df[["c", "a", "b"]])


@settings(max_examples=50, deadline=None)
@given(df=frames)
def test_fingerprint_sees_a_duplicate_a_rename_and_a_dropped_row(df):
    if len(df):
        assert fingerprint(df) != fingerprint(pd.concat([df, df.iloc[[0]]]))  # multiset, not set
        assert fingerprint(df) != fingerprint(df.iloc[1:])
    assert fingerprint(df) != fingerprint(df.rename(columns={"a": "z"}))


@settings(max_examples=40, deadline=None)
@given(values=st.lists(st.integers(-10, 10), min_size=1, max_size=12))
def test_fingerprint_does_not_depend_on_integer_or_float_storage(values):
    ints = pd.DataFrame({"v": values})
    floats = pd.DataFrame({"v": [float(v) for v in values]})
    assert fingerprint(ints) == fingerprint(floats)


# ----------------------------------------------------------------------------- station matching


@settings(max_examples=40, deadline=None)
@given(n=st.integers(1, 12), seed=st.integers(0, 9999))
def test_identical_inventories_match_themselves_whatever_the_order(n, seed):
    rng = np.random.default_rng(seed)
    old = pd.DataFrame(
        {
            "station_id": [f"s{i}" for i in range(n)],
            "name": [f"Station {i}" for i in range(n)],
            "lat": 43.6 + rng.random(n) * 0.05,
            "lon": 3.87 + rng.random(n) * 0.05,
        }
    )
    new = old.sample(frac=1.0, random_state=seed).reset_index(drop=True)
    m = match_stations(old, new)
    assert (m["match_method"] == "same_id").all() and len(m) == n
    assert (m["station_id_old"] == m["station_id_new"]).all()
    assert (m["distance_m"].fillna(0) >= 0).all()
    assert set(m["match_method"]) <= set(METHODS)


@settings(max_examples=40, deadline=None)
@given(n=st.integers(1, 10), seed=st.integers(0, 9999), jitter=st.floats(0, 40))
def test_renumbered_stations_are_followed_by_position_within_the_radius(n, seed, jitter):
    rng = np.random.default_rng(seed)
    lat = 43.6 + np.arange(n) * 0.01  # about a kilometre apart: no ambiguity
    lon = np.full(n, 3.87)
    old = pd.DataFrame({"station_id": [f"o{i}" for i in range(n)], "lat": lat, "lon": lon})
    shift = jitter / 111_000.0 * rng.choice([-1, 1], n)  # metres to degrees of latitude
    new = pd.DataFrame({"station_id": [f"n{i}" for i in range(n)], "lat": lat + shift, "lon": lon})
    m = match_stations(old, new)
    paired = m.dropna(subset=["station_id_old", "station_id_new"])
    assert len(paired) == n
    assert (paired["station_id_old"].str[1:] == paired["station_id_new"].str[1:]).all()


# ----------------------------------------------------------------------------- the lake


@settings(max_examples=20, deadline=None)
@given(df=snapshots(max_rows=40))
def test_lake_round_trip_keeps_every_row_and_merge_is_idempotent(df, tmp_path_factory):
    pytest.importorskip("pyarrow")
    from gbfs_toolkit.store import read_lake, write_lake

    root = tmp_path_factory.mktemp("lake")
    frame = df.rename(columns={"fetched_at": "observed_at_utc"})
    write_lake(frame, root / "a")
    back = read_lake(root / "a")
    assert len(back) == len(frame)
    assert fingerprint(back, exclude=()) == fingerprint(frame.assign(system_id=frame["system_id"]))
    write_lake(frame, root / "m", mode="merge")
    once = read_lake(root / "m")
    write_lake(frame, root / "m", mode="merge")
    twice = read_lake(root / "m")
    assert len(once) == len(twice) == len(frame)  # rows are distinct, so merge keeps them all
    assert fingerprint(once) == fingerprint(twice)


@settings(max_examples=10, deadline=None)
@given(df=snapshots(max_rows=40))
def test_a_frozen_release_is_the_same_twice(df, tmp_path_factory):
    pytest.importorskip("pyarrow")
    from gbfs_toolkit.release import freeze_release, verify_release
    from gbfs_toolkit.store import write_lake

    root = tmp_path_factory.mktemp("rel")
    write_lake(df.rename(columns={"fetched_at": "observed_at_utc"}), root / "lake")
    kw = {
        "name": "demo",
        "start": "2026-03-01",
        "end": "2026-03-04",
        "license": "CC0-1.0",
        "today": dt.date(2026, 4, 1),
    }
    one = freeze_release(root / "lake", root / "one", **kw)
    two = freeze_release(root / "lake", root / "two", **kw)
    assert verify_release(root / "one", strict=False)["ok"]
    assert one["rows"] == two["rows"] == len(df)
    data = lambda r: sorted((root / r / "data").rglob("*.parquet"))  # noqa: E731
    assert [p.read_bytes() for p in data("one")] == [p.read_bytes() for p in data("two")]
    assert (root / "one" / "SHA256SUMS").exists()

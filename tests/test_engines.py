"""The engines of `aggregate`, `quality` and `store` agree, whatever the source.

A pandas frame, an Arrow table, a DuckDB relation and a lake path give the same result, and so
does the window-by-window pandas computation that replaces DuckDB when it is not installed.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

pa = pytest.importorskip("pyarrow")
duckdb = pytest.importorskip("duckdb")

from gbfs_toolkit.aggregate import (  # noqa: E402
    aggregate_availability,
    aggregate_levels,
    check_conservation,
)
from gbfs_toolkit.core.errors import GBFSValidationError  # noqa: E402
from gbfs_toolkit.store import write_lake  # noqa: E402


def make_snapshots(seed: int = 0, n_systems: int = 2, n_stations: int = 4, hours: int = 60):
    """Irregular polls with holes, missing counts, flags and a few repeated instants."""
    rng = np.random.default_rng(seed)
    frames = []
    base = pd.Timestamp("2026-03-27T21:30:00Z")  # crosses a day boundary and a clock change
    for s in range(n_systems):
        for k in range(n_stations):
            n = hours * 20
            offs = np.sort(rng.integers(0, hours * 3600, size=n))
            offs = np.concatenate([offs, offs[:5]])  # repeated instants (ties)
            t = base + pd.to_timedelta(offs, unit="s")
            bikes = rng.integers(0, 15, size=len(t)).astype("float64")
            bikes[rng.random(len(t)) < 0.05] = np.nan
            docks = rng.integers(0, 15, size=len(t)).astype("float64")
            docks[rng.random(len(t)) < 0.05] = np.nan
            frames.append(
                pd.DataFrame(
                    {
                        "system_id": f"sys{s}",
                        "station_id": f"st{k}",
                        "fetched_at": t,
                        "num_bikes_available": bikes,
                        "num_docks_available": docks if k % 2 == 0 else np.nan,
                        "capacity": 14 if k % 3 else np.nan,
                        "is_renting": rng.random(len(t)) < 0.9,
                        "both_zero_suspect": rng.random(len(t)) < 0.03,
                    }
                )
            )
    df = pd.concat(frames, ignore_index=True)
    return df.sample(frac=1.0, random_state=seed).reset_index(drop=True)  # unsorted input


def assert_same(a: pd.DataFrame, b: pd.DataFrame) -> None:
    """Counts and integers identical, floats equal to rounding."""
    assert list(a.columns) == list(b.columns)
    assert len(a) == len(b)
    for c in a.columns:
        if c in ("system_id", "station_id", "bucket_start_utc", "bucket_start_local"):
            assert (a[c].to_numpy() == b[c].to_numpy()).all(), c
        elif str(a[c].dtype) in ("int64", "Int64", "Int16"):
            assert a[c].equals(b[c]), c
            assert str(a[c].dtype) == str(b[c].dtype), c
        else:
            np.testing.assert_allclose(
                a[c].astype("float64"), b[c].astype("float64"), rtol=1e-9, atol=1e-9, err_msg=c
            )


@pytest.fixture(scope="module")
def snaps():
    return make_snapshots()


@pytest.mark.parametrize("freq", ["15min", "1h", "1D", "7min"])
def test_every_source_and_engine_gives_the_same_aggregate(snaps, freq, tmp_path):
    reference = aggregate_availability(snaps, freq, tz="Europe/Paris")
    assert int(reference["n_obs"].sum()) == len(snaps)
    table = pa.Table.from_pandas(snaps, preserve_index=False)
    lake = tmp_path / "lake"
    write_lake(snaps.rename(columns={"fetched_at": "observed_at_utc"}), lake)
    sources = {
        "duckdb on a frame": (snaps, "duckdb"),
        "duckdb on arrow": (table, "auto"),
        "duckdb on a relation": (duckdb.from_arrow(table), "auto"),
        "pandas by windows on arrow": (table, "pandas"),
    }
    for name, (source, engine) in sources.items():
        got = aggregate_availability(source, freq, tz="Europe/Paris", engine=engine, chunk="6h")
        assert_same(reference, got)
        check_conservation(got, source)
        assert int(got["n_obs"].sum()) == len(snaps), name
    # a lake path: the time column is named observed_at_utc there
    for engine in ("auto", "duckdb", "pandas"):
        got = aggregate_availability(
            lake, freq, tz="Europe/Paris", time_col="observed_at_utc", engine=engine, chunk="5h"
        )
        assert_same(reference, got)


def test_windows_do_not_cut_a_pair_of_rows_or_a_bucket(snaps):
    """Whatever the window, the carried row keeps the movement across a boundary."""
    table = pa.Table.from_pandas(snaps, preserve_index=False)
    reference = aggregate_availability(snaps, "1h")
    for chunk in ("1h", "90min", "3h", "1D", "10D"):
        got = aggregate_availability(table, "1h", engine="pandas", chunk=chunk)
        assert_same(reference, got)


def test_a_frame_with_a_gapped_index_keeps_pct_full_and_pct_renting():
    """A non-default index used to blank the columns that read `capacity` and `is_renting`."""
    t = pd.date_range("2026-03-01T08:00Z", periods=6, freq="min")
    df = pd.DataFrame(
        {
            "system_id": "a",
            "station_id": "s",
            "fetched_at": t,
            "num_bikes_available": [1, 2, 3, 4, 5, 6],
            "capacity": 6,
            "is_renting": True,
        },
        index=[10, 11, 12, 13, 14, 15],
    )
    row = aggregate_availability(df, "1h").iloc[0]
    assert float(row["pct_renting"]) == 100.0 and float(row["pct_full"]) == pytest.approx(100 / 6)
    reversed_ = aggregate_availability(df.iloc[::-1], "1h").iloc[0]
    assert float(reversed_["pct_full"]) == pytest.approx(float(row["pct_full"]))


def test_levels_conserve_observations_in_every_engine(snaps):
    table = pa.Table.from_pandas(snaps, preserve_index=False)
    for engine in ("duckdb", "pandas"):
        levels = aggregate_levels(table, engine=engine, chunk="12h")
        assert {k: int(v["n_obs"].sum()) for k, v in levels.items()} == {
            "15m": len(snaps),
            "1h": len(snaps),
            "1d": len(snaps),
        }


def test_conservation_check_reads_any_source(snaps):
    table = pa.Table.from_pandas(snaps, preserve_index=False)
    agg = aggregate_availability(table, "1h")
    check_conservation(agg, table)
    with pytest.raises(GBFSValidationError, match="does not conserve"):
        check_conservation(agg.iloc[:-1], table)


def test_empty_sources_and_bad_arguments(snaps):
    empty = pa.Table.from_pandas(snaps.iloc[:0], preserve_index=False)
    for engine in ("duckdb", "pandas"):
        out = aggregate_availability(empty, "1h", engine=engine)
        assert out.empty and list(out.columns)[:3] == [
            "system_id",
            "station_id",
            "bucket_start_utc",
        ]
    with pytest.raises(ValueError, match="engine"):
        aggregate_availability(snaps, "1h", engine="spark")
    text_time = snaps.assign(fetched_at=snaps["fetched_at"].astype(str))
    with pytest.raises(ValueError, match="timestamp"):
        aggregate_availability(pa.Table.from_pandas(text_time, preserve_index=False), "1h")
    with pytest.raises(TypeError, match="Arrow table"):
        aggregate_availability(42, "1h")  # type: ignore[arg-type]
    with pytest.raises(FileNotFoundError):
        aggregate_availability("/nonexistent/lake", "1h")


def test_a_plain_folder_of_parquet_files_is_a_source(snaps, tmp_path):
    cuts = [0, len(snaps) // 3, 2 * len(snaps) // 3, len(snaps)]
    for i in range(3):
        snaps.iloc[cuts[i] : cuts[i + 1]].to_parquet(tmp_path / f"p{i}.parquet", index=False)
    got = aggregate_availability(tmp_path, "1h")
    assert_same(aggregate_availability(snaps, "1h"), got)
    one = aggregate_availability(str(tmp_path / "p0.parquet"), "1h", engine="pandas")
    assert int(one["n_obs"].sum()) == cuts[1]


def test_without_duckdb_auto_falls_back_to_the_windowed_pandas_engine(snaps, monkeypatch):
    from gbfs_toolkit.core import _tabular

    monkeypatch.setattr(_tabular, "has_duckdb", lambda: False)
    table = pa.Table.from_pandas(snaps, preserve_index=False)
    assert _tabular.resolve_engine("auto", _tabular.open_table(table)) == "pandas"
    assert_same(
        aggregate_availability(snaps, "1h"),
        aggregate_availability(table, "1h", chunk="4h"),
    )

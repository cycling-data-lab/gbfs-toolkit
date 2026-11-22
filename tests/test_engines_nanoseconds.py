"""Parquet files written with nanosecond timestamps go through the DuckDB engine.

pandas 2 writes ``timestamp[ns]`` columns, which DuckDB reads as ``TIMESTAMP_NS`` or
``TIMESTAMPTZ_NS``. ``epoch_us`` has no overload for ``TIMESTAMPTZ_NS``, so every SQL time
expression goes through ``epoch_ns(...) // 1000``. This test pins that, whatever the pandas
version that runs the suite (pandas 3 writes microseconds by default).
"""

from __future__ import annotations

import pandas as pd
import pytest

pa = pytest.importorskip("pyarrow")
pq = pytest.importorskip("pyarrow.parquet")
pytest.importorskip("duckdb")

from gbfs_toolkit import quality  # noqa: E402
from gbfs_toolkit.aggregate import aggregate_availability  # noqa: E402

from test_engines import assert_same, make_snapshots  # noqa: E402


def _write_nanoseconds(df: pd.DataFrame, path, *, tz: bool) -> None:
    table = pa.Table.from_pandas(df, preserve_index=False)
    unit = pa.timestamp("ns", tz="UTC") if tz else pa.timestamp("ns")
    times = df["fetched_at"]
    if not tz:
        times = times.dt.tz_convert("UTC").dt.tz_localize(None)
    column = pa.array(times.astype("datetime64[ns, UTC]" if tz else "datetime64[ns]"), type=unit)
    table = table.set_column(table.schema.get_field_index("fetched_at"), "fetched_at", column)
    pq.write_table(table, path)


@pytest.mark.parametrize("tz", [True, False], ids=["timestamptz_ns", "timestamp_ns"])
def test_nanosecond_parquet_aggregates_like_the_frame(tmp_path, tz):
    snaps = make_snapshots(seed=3, hours=30)
    path = tmp_path / "ns.parquet"
    _write_nanoseconds(snaps, path, tz=tz)
    frame = (
        snaps
        if tz
        else snaps.assign(fetched_at=snaps["fetched_at"].dt.tz_convert("UTC").dt.tz_localize(None))
    )
    expected = aggregate_availability(frame, "1h", engine="pandas")
    got = aggregate_availability(str(path), "1h", engine="duckdb")
    assert_same(expected, got)


def test_nanosecond_parquet_daily_coverage_runs_on_duckdb(tmp_path):
    snaps = make_snapshots(seed=4, hours=30)
    path = tmp_path / "ns.parquet"
    _write_nanoseconds(snaps, path, tz=True)
    expected = quality.daily_coverage(snaps)
    got = quality.daily_coverage(str(path))
    pd.testing.assert_frame_equal(
        expected.reset_index(drop=True), got.reset_index(drop=True), check_dtype=False
    )

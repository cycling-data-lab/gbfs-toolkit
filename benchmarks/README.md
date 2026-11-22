# Benchmarks

* `test_benchmarks.py` : micro-benchmarks of the heaviest descriptive functions
  (`pytest benchmarks/ --benchmark-only`, run informationally in CI).
* `lake_volume.py` : the large-volume paths on a synthetic lake of tens of millions of rows. Run by hand:

  ```bash
  python benchmarks/lake_volume.py --workdir ~/.cache/gbfs-bench          # 42 million rows
  python benchmarks/lake_volume.py --workdir /tmp/bench --stations 400 --days 7   # a quick look
  GBFS_TOOLKIT_DUCKDB_MEMORY_LIMIT=6GB GBFS_TOOLKIT_DUCKDB_THREADS=8 python benchmarks/lake_volume.py ...
  ```

  Every step runs in its own process, so its peak memory is its own. The data are random; nothing real
  is used. Use a working directory on disk (the lake is small, but a tmpfs is memory).

## Last run (22 November 2026)

A laptop with 16 logical CPUs and 15 GB of memory (other programs running), Python 3.12, pandas 3.1,
pyarrow 26, DuckDB 2.0. One system, 1000 stations polled every minute for 30 days with a four-hour
hole once a week: **42,240,000 rows**, 45 MB of Parquet (zstd; the random walks compress well).
DuckDB was capped at 6 GB and 8 threads.

| Step | What | Time | Peak memory |
|---|---|---|---|
| `aggregate_duckdb` | 15 min, hour and day tables, from the lake folder | 72 s | 5.7 GB (the cap) |
| `aggregate_pandas_windows` | the same, window by window in pandas (no DuckDB) | 190 s | 2.0 GB |
| `coverage_duckdb` | daily coverage, gaps, incidents (`assess`) from the folder | 1.9 s | 0.7 GB |
| `coverage_pandas_batches` | the same, in batches of pandas | 13 s | 1.3 GB |
| `aggregate_pandas_frame` | a **frame of 2 days** (2.88 M rows), 15 min level only | 14 s | 5.9 GB |
| `write_lake_from_path` | the whole lake written into another one, a day at a time | 7.7 s | 0.7 GB |

The two engines gave the same 2,816,000 buckets: same keys, identical integer columns, floating-point
columns equal to 1e-9 relative, and `n_obs` summing to 42,240,000 at every level.

Reading the table: the frame path needs about 2 GB of memory per million rows for this aggregate (the frame,
its sorted copy and the intermediate columns), so it stops being enough around two or three million rows on
a 16 GB machine, which is two days of a 1000-station system at a poll a minute. DuckDB reads the lake in
place and is the fastest; the pandas windows use a window's worth of memory (about 2 GB for a day of
1.44 M rows) and take about 2.6 times as long. The raw result is `results/lake_volume-2026-11-22.json`.

"""Measure the large-volume paths on a synthetic lake of tens of millions of rows.

Not a unit test and not collected by ``pytest benchmarks/`` (the name does not start with
``test_``): run it by hand::

    python benchmarks/lake_volume.py --workdir /tmp/gbfs-bench                # 43 million rows
    python benchmarks/lake_volume.py --workdir /tmp/gbfs-bench --stations 400 --days 7   # quick

What it does:

1. writes a synthetic lake (one system, ``--stations`` stations polled every minute for
   ``--days`` days, so 1000 x 30 x 1440 = 43.2 million rows by default) in the layout of
   `gbfs_toolkit.store`, one Parquet file per day, with a few missing counts and a few
   collection holes. The data is random; nothing real is used;
2. runs each measured step in its own process, so that the peak memory is the step's own:
   the three aggregation levels and the coverage report on DuckDB, the same two on pandas
   window by window (what runs when DuckDB is not installed), the same aggregate on a plain
   in-memory frame of ``--frame-days`` days (to show where that path stops being enough),
   and the write of the whole lake into a second lake;
3. checks that the DuckDB and the windowed-pandas aggregates agree and conserve ``n_obs``;
4. prints a table (and writes ``results.json`` in the working directory).

The numbers depend on the machine; the point is the shape: seconds and a bounded memory for
the engines that read the lake in place, against a memory that grows with the rows for a frame.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import resource
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

SYSTEM = "bench"
START = pd.Timestamp("2026-03-01", tz="UTC")


def build_lake(root: Path, stations: int, days: int, seed: int = 0) -> int:
    """Write the synthetic lake and return its number of rows."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    rng = np.random.default_rng(seed)
    ids = np.array([f"st{i:04d}" for i in range(stations)])
    capacity = rng.integers(10, 40, stations)
    level = (capacity * rng.random(stations)).astype("int32")
    total = 0
    minutes = np.arange(1440)
    for d in range(days):
        day = START + pd.Timedelta(days=d)
        folder = root / f"system_id={SYSTEM}" / f"year={day.year:04d}" / f"month={day.month:02d}"
        folder.mkdir(parents=True, exist_ok=True)
        # a reflecting random walk per station, minute by minute, inside [0, capacity]: a bike
        # leaves or arrives in about 6 % of the minutes
        steps = rng.choice([-1, 0, 1], p=[0.03, 0.94, 0.03], size=(1440, stations)).astype("int32")
        raw = level + np.cumsum(steps, axis=0)
        folded = np.mod(raw, 2 * capacity)
        walk = np.where(folded > capacity, 2 * capacity - folded, folded).astype("int32")
        level = walk[-1]
        keep = np.ones(1440, bool)
        if d % 7 == 3:
            keep[120:360] = False  # a collection hole of four hours, every week
        m = minutes[keep]
        bikes = walk[keep]
        n = len(m) * stations
        t = (day + pd.to_timedelta(np.repeat(m, stations), unit="min")).to_numpy()
        bikes_flat = bikes.reshape(-1)
        docks_flat = (capacity[None, :] - bikes).reshape(-1)
        missing = rng.random(n) < 0.002
        table = pa.table(
            {
                "station_id": pa.array(np.tile(ids, len(m))),
                "observed_at_utc": pa.array(
                    t.astype("datetime64[us]").astype("int64"), pa.int64()
                ).cast(pa.timestamp("us", tz="UTC")),
                "num_bikes_available": pa.array(bikes_flat, mask=missing, type=pa.int32()),
                "num_docks_available": pa.array(docks_flat, mask=missing, type=pa.int32()),
                "capacity": pa.array(np.tile(capacity, len(m)), type=pa.int32()),
            }
        )
        pq.write_table(table, folder / f"part-{d:03d}.parquet", compression="zstd")
        total += n
    return total


def peak_mb() -> float:
    """Peak resident memory of this process, in MB (Linux and macOS report different units)."""
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / (1024 * 1024) if sys.platform == "darwin" else peak / 1024


def run_step(name: str, lake: str, workdir: str, frame_days: int) -> dict:
    """Run one measured step in this process; the parent calls it through a subprocess."""
    from gbfs_toolkit.aggregate import aggregate_availability, aggregate_levels
    from gbfs_toolkit.quality import assess
    from gbfs_toolkit.store import read_lake, write_lake

    tcol = "observed_at_utc"
    t0 = time.perf_counter()
    info: dict = {}
    if name in ("aggregate_duckdb", "aggregate_pandas_windows"):
        engine = "duckdb" if name.endswith("duckdb") else "pandas"
        out = aggregate_levels(lake, engine=engine, time_col=tcol, chunk="1D")
        info["rows_in"] = int(out["15m"]["n_obs"].sum())
        info["buckets_15m"] = int(len(out["15m"]))
        out["15m"].to_parquet(Path(workdir) / f"{name}.parquet")
    elif name in ("coverage_duckdb", "coverage_pandas_batches"):
        engine = "duckdb" if name.endswith("duckdb") else "pandas"
        report = assess(lake, time_col=tcol, engine=engine)
        info["system_days"] = int(len(report.coverage))
        info["days_by_status"] = report.summary()["days_by_status"]
    elif name == "aggregate_pandas_frame":
        frame = read_lake(lake, end=START + pd.Timedelta(days=frame_days))
        info["rows_in"] = int(len(frame))
        out = aggregate_availability(frame.assign(system_id=SYSTEM), "15min", time_col=tcol)
        info["buckets_15m"] = int(len(out))
    elif name == "write_lake_from_path":
        target = Path(workdir) / "copy"
        touched = write_lake(lake, target)
        info["partitions"] = int(len(touched))
        info["rows_in"] = int(touched["rows"].sum())
    else:  # pragma: no cover
        raise SystemExit(f"unknown step {name}")
    return {
        "step": name,
        "seconds": round(time.perf_counter() - t0, 2),
        "peak_mb": round(peak_mb()),
        **info,
    }


STEPS = [
    "aggregate_duckdb",
    "aggregate_pandas_windows",
    "coverage_duckdb",
    "coverage_pandas_batches",
    "aggregate_pandas_frame",
    "write_lake_from_path",
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--workdir", required=True, help="where the lake and the results go")
    ap.add_argument("--stations", type=int, default=1000)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument(
        "--frame-days",
        type=int,
        default=2,
        dest="frame_days",
        help="days loaded as a pandas frame for the in-memory baseline (default 2)",
    )
    ap.add_argument("--steps", nargs="+", choices=STEPS, default=STEPS)
    ap.add_argument("--step", help=argparse.SUPPRESS)
    ap.add_argument("--lake", help=argparse.SUPPRESS)
    args = ap.parse_args()

    if args.step:  # child process: one step, JSON on stdout
        print(json.dumps(run_step(args.step, args.lake, args.workdir, args.frame_days)))
        return 0

    work = Path(args.workdir)
    lake = work / "lake"
    if not lake.exists():
        t0 = time.perf_counter()
        rows = build_lake(lake, args.stations, args.days)
        print(f"built {rows:,} rows in {time.perf_counter() - t0:.0f} s")
    size = sum(f.stat().st_size for f in lake.rglob("*.parquet"))
    results = []
    for step in args.steps:
        cmd = [
            sys.executable,
            __file__,
            "--workdir",
            str(work),
            "--step",
            step,
            "--lake",
            str(lake),
            "--frame-days",
            str(args.frame_days),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False, env=os.environ)
        if proc.returncode != 0:
            results.append({"step": step, "error": proc.stderr.strip().splitlines()[-1:]})
            continue
        results.append(json.loads(proc.stdout.strip().splitlines()[-1]))
        print(results[-1])

    verdict = {}
    a, b = work / "aggregate_duckdb.parquet", work / "aggregate_pandas_windows.parquet"
    if a.exists() and b.exists():
        x, y = pd.read_parquet(a), pd.read_parquet(b)
        keys = ["system_id", "station_id", "bucket_start_utc"]
        same_keys = bool((x[keys].to_numpy() == y[keys].to_numpy()).all()) and len(x) == len(y)
        floats = [c for c in x.columns if c.startswith(("bikes_mean", "docks_mean", "pct_"))]
        close = all(
            np.allclose(x[c].astype(float), y[c].astype(float), rtol=1e-9, equal_nan=True)
            for c in floats
        )
        ints = all(
            x[c].astype("Int64").equals(y[c].astype("Int64"))
            for c in ("n_obs", "n_valid", "bikes_min", "bikes_max", "movement_volume")
        )
        verdict = {"same_buckets": same_keys, "floats_agree": close, "integers_identical": ints}
    payload = {
        "machine": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "cpus": os.cpu_count(),
        },
        "lake": {"stations": args.stations, "days": args.days, "parquet_mb": round(size / 1e6)},
        "results": results,
        "engines_agree": verdict,
    }
    (work / "results.json").write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

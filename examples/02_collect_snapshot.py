"""One collection run, meant to be driven by cron (not a loop in here).

    */2 * * * * python 02_collect_snapshot.py velib /data/velib_lake

Polls station_status once, appends it to a Hive-partitioned Parquet lake, and remembers
the feed's ETag so the next run can skip the download when nothing changed. Keeping the
schedule outside the library is deliberate — the toolkit collects, your orchestrator decides
when. Run it every few minutes for a few weeks and you have a panel.
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

import gbfs_toolkit as gb


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("system_id", help="MobilityData catalogue id, e.g. 'velib'")
    ap.add_argument("lake", type=Path)
    args = ap.parse_args()

    feed = gb.GBFSFeed.from_system_id(args.system_id)
    status_url = feed.feeds.get("station_status")
    if status_url is None:
        sys.exit(f"{args.system_id} has no station_status feed")

    # conditional GET: don't re-download an unchanged snapshot
    state_file = args.lake / f".{args.system_id}.etag"
    etag = state_file.read_text().strip() if state_file.exists() else None
    session = gb.build_session()
    try:
        resp = gb.fetch_feed_json(status_url, session=session, etag=etag)
    except gb.GBFSNotModified:
        return  # nothing new; cron will try again later

    status = gb.to_canonical_station_status(
        resp.data, system_id=args.system_id, fetched_at=pd.Timestamp.now(tz="UTC")
    )
    gb.append_to_parquet(status, args.lake)

    if resp.etag:
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(resp.etag)

    print(f"{args.system_id}: appended {len(status)} rows")


if __name__ == "__main__":
    main()

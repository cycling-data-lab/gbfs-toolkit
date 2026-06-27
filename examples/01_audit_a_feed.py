"""First contact with an unknown feed: what's in it, and what can I trust?

    python 01_audit_a_feed.py https://example.com/gbfs.json --system-id mycity

Most operator feeds have *something* wrong with them — a block of stations at (0, 0),
a placeholder capacity copied across the whole network, car-share parking dressed up as
bike-share. The point here is to see the damage before it leaks into a model.
"""

import argparse

import gbfs_toolkit as gb


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("gbfs_url")
    ap.add_argument("--system-id", default="system")
    args = ap.parse_args()

    feed = gb.GBFSFeed.from_url(args.gbfs_url, system_id=args.system_id)
    print(feed.summary(), end="\n\n")

    stations = feed.station_information()
    verdict = gb.audit_static(stations)

    flagged = verdict[verdict["flagged"]]
    print(f"{len(flagged)} of {len(verdict)} stations flagged\n")
    if not flagged.empty:
        # which problems, and how often
        print(flagged["reason"].value_counts().to_string(), end="\n\n")

    # keep the analysable subset; this is what everything downstream should use
    clean = stations[~verdict["flagged"].to_numpy()].reset_index(drop=True)
    print(f"{len(clean)} stations kept for analysis")

    # if the feed is live, the dynamic checks catch negative counts / staleness too
    if feed.has("station_status"):
        dyn = gb.audit_dynamic(feed.availability(), ttl_seconds=feed.ttl)
        print(
            f"{int(dyn['flagged'].sum())} stations with live-data problems "
            f"({', '.join(sorted(set(dyn[dyn.flagged]['reason']))) or 'none'})"
        )


if __name__ == "__main__":
    main()

"""After a few weeks of collecting: turn the lake into something you can write about.

    python 03_analyze_history.py /data/velib_lake --system-id velib --tz Europe/Paris

Three things a reviewer will ask for: how complete is the data, what does a typical day
look like, and can the stations be grouped by behaviour. Coverage first — there's no point
clustering rhythms from a station that was offline half the month.
"""

import argparse
from pathlib import Path

import gbfs_toolkit as gb


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("lake", type=Path)
    ap.add_argument("--system-id", default="velib")
    ap.add_argument("--tz", default="Europe/Paris", help="local tz for diurnal analysis")
    args = ap.parse_args()

    # convert to local time *before* any daily aggregation, or rush hour lands at the wrong hour
    panel = gb.build_availability_panel(args.lake, system_id=args.system_id, target_tz=args.tz)

    cov = gb.coverage_report(panel)
    print(
        f"median uptime {cov['uptime_pct'].median():.0f}% "
        f"({(cov['uptime_pct'] > 90).mean():.0%} of stations above 90%)\n"
    )

    # only trust stations we actually observed most of the time
    well_observed = cov.index[cov["uptime_pct"] > 80].get_level_values("station_id")
    panel = panel[panel.index.get_level_values("station_id").isin(well_observed)]

    typ = gb.cluster_diurnal_profiles(panel, n_clusters="auto", normalize="zscore")
    labels = gb.label_diurnal_typology(typ.set_index(["system_id", "station_id"]))
    print("station typologies:")
    print(labels.value_counts().to_string(), end="\n\n")

    flow = gb.calculate_net_flow(panel)
    busiest = (
        flow.assign(activity=flow["net_flow"].abs())
        .groupby("station_id")["activity"]
        .sum()
        .sort_values(ascending=False)
        .head(5)
    )
    print("most active stations (lower-bound turnover):")
    print(busiest.to_string())


if __name__ == "__main__":
    main()

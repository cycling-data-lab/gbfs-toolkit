"""Is the network spread fairly, or piled into a few downtown hubs?

    python 04_equity_and_coverage.py https://example.com/gbfs.json

Two angles. Capacity concentration (Gini / Lorenz) asks whether the bikes are shared out or
hoarded. Spatial dispersion (density, Clark-Evans, Moran's I on occupancy) asks whether the
geography and the demand are clustered. If a feed publishes geofencing zones we measure
density against the real service area instead of a convex hull, which matters a lot for
free-floating systems.
"""

import argparse

import gbfs_toolkit as gb


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("gbfs_url")
    ap.add_argument("--system-id", default="system")
    args = ap.parse_args()

    feed = gb.GBFSFeed.from_url(args.gbfs_url, system_id=args.system_id)
    info = feed.station_information()

    conc = gb.concentration_metrics(info)
    print(
        f"capacity Gini {conc['gini']:.2f}, "
        f"top 10% of stations hold {conc['top_decile_share']:.0%} of capacity\n"
    )

    zones = feed.geofencing_zones() if feed.has("geofencing_zones") else None
    cov = gb.coverage_stats(info, zones=zones)
    area = cov.get("service_area_km2", cov.get("hull_area_km2"))
    print(
        f"{cov['n_stations']} stations over ~{area:.1f} km² "
        f"({cov['stations_per_km2']:.1f}/km²), "
        f"nearest-neighbour {cov['mean_nearest_neighbor_m']:.0f} m, "
        f"Clark-Evans {cov['clark_evans_index']:.2f}"
    )

    # is low availability geographically clustered right now? (equity signal)
    if feed.has("station_status"):
        av = feed.availability()
        av = av.assign(
            occ=av["num_bikes_available"] / (av["num_bikes_available"] + av["num_docks_available"])
        )
        mi = gb.morans_i(av.dropna(subset=["occ", "lat", "lon"]), "occ")
        verdict = "clustered" if mi["morans_i"] > mi["expected_i"] else "dispersed"
        print(f"\noccupancy Moran's I {mi['morans_i']:.2f} ({verdict}, p={mi['p_value']:.3f})")


if __name__ == "__main__":
    main()

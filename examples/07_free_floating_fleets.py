"""Audit a free-floating (and hybrid) fleet: ghosts and spatial collapse.

Self-contained (synthetic free-floating panel + a docked snapshot, no network):

    python 07_free_floating_fleets.py

Free-floating systems break the station paradigm: the truth lives in
``free_bike_status``/``vehicles``, not ``station_status``. This reconciles both
sides into one tally, flags vehicles that never move (declared but inactive
"ghosts" inflating the advertised supply), and measures whether the live fleet
collapses into a few blocks (a falling spatial entropy).
"""

import pandas as pd

import gbfs_toolkit as gb


def main() -> None:
    # Three daily snapshots. g1/g2 never move (ghosts); m1-m3 roam the city.
    days = pd.to_datetime(["2026-06-01T08:00Z", "2026-06-02T08:00Z", "2026-06-03T08:00Z"])
    tracks = {
        "g1": [(48.850, 2.350)] * 3,
        "g2": [(48.860, 2.360)] * 3,
        "m1": [(48.850, 2.350), (48.870, 2.380), (48.880, 2.390)],
        "m2": [(48.860, 2.360), (48.840, 2.340), (48.835, 2.330)],
        "m3": [(48.852, 2.362), (48.866, 2.372), (48.874, 2.362)],
    }
    vehicles = pd.DataFrame(
        [
            {
                "system_id": "ff",
                "vehicle_id": vid,
                "lat": la,
                "lon": lo,
                "fetched_at": t,
                "is_disabled": False,
                "is_reserved": False,
            }
            for vid, pts in tracks.items()
            for t, (la, lo) in zip(days, pts, strict=True)
        ]
    )

    # A docked snapshot for the hybrid side.
    station_status = pd.DataFrame(
        {
            "system_id": "ff",
            "station_id": ["s1", "s2"],
            "num_bikes_available": [4, 7],
            "num_docks_available": [6, 3],
        }
    )

    # 1. One labelled tally across docked + free-floating (latest snapshot).
    latest = vehicles[vehicles["fetched_at"] == days[-1]]
    print(
        "Reconciled fleet tally:", gb.reconcile_fleet_state(station_status, latest).to_dict(), "\n"
    )

    # 2. Ghost vehicles: present in the feed but immobile over the panel.
    ghosts = gb.detect_ghost_vehicles(vehicles, idle_days=1.0, move_threshold_m=50.0).reset_index()
    flagged = ghosts.loc[ghosts["is_ghost"], "vehicle_id"].tolist()
    print("Ghost vehicles (declared but never moved):", flagged, "\n")

    # 3. Spatial entropy of the free-floating distribution over time (higher = spread).
    ent = gb.spatial_entropy(vehicles, grid_size_m=2000)
    print("Spatial entropy per snapshot:")
    print(
        ent[["fetched_at", "n_vehicles", "shannon_entropy", "evenness"]]
        .round(3)
        .to_string(index=False)
    )


if __name__ == "__main__":
    main()

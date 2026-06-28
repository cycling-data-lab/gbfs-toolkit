"""Service reliability: how long do stockouts last, and is sampling hiding them?

Self-contained (synthetic availability panel, no network):

    python 08_service_reliability.py

Moves the question from *quantity* (how many bikes) to *resilience* (how long a
station stays unusable). It extracts stockout episodes, fits a descriptive
Kaplan–Meier survival curve of their durations (with the right-censoring stated,
never imputed), checks whether the collection cadence is fast enough to see the
real dynamics, and measures how peaked the activity is across the day.
"""

import numpy as np
import pandas as pd

import gbfs_toolkit as gb


def main() -> None:
    # One station, 24 h at a 15-minute cadence. Two stockouts: a short morning one
    # and a long evening one (the fleet drained and not rebalanced until late).
    times = pd.date_range("2026-06-01T00:00Z", periods=96, freq="15min")
    t = np.arange(96)
    bikes = np.clip(
        12 - 14 * np.exp(-((t - 32) ** 2) / 12) - 13 * np.exp(-((t - 76) ** 2) / 40), 0, 20
    )
    bikes = bikes.round().astype(int)
    panel = pd.DataFrame(
        {
            "system_id": "s",
            "station_id": "a",
            "fetched_at": times,
            "num_bikes_available": bikes,
            "num_docks_available": 20 - bikes,
        }
    )

    # 1. Stockout episodes (contiguous spells at a saturation boundary).
    episodes = gb.stockout_episodes(panel, kinds=("empty",))
    print("Stockout episodes (empty):")
    print(episodes[["station_id", "kind", "duration_minutes"]].to_string(index=False), "\n")

    # 2. Kaplan–Meier survival of episode duration (descriptive; censoring stated).
    surv = gb.outage_survival(episodes)
    print("Outage survival (P(empty spell lasts > t)):")
    print(surv.round(3).to_string(index=False), "\n")

    # 3. Is the 15-minute cadence fast enough to see the real signal?
    print("Sampling vulnerability:")
    print(gb.aliasing_vulnerability(panel).round(3).to_string(index=False), "\n")

    # 4. How concentrated is the day's activity (1 = all in one hour)?
    print("Temporal concentration:")
    print(gb.temporal_concentration(panel).round(3).to_string(index=False))


if __name__ == "__main__":
    main()

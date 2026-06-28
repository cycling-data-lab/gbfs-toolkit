"""Equity, accessibility and the signature rebalancing-tension metric.

Self-contained (bundled ``load_example`` plus small synthetic frames, no network):

    python 06_equity_rebalancing.py

Three research angles a transport-geography study would want: how unequally the
supply is shared (Theil decomposition, Palma ratio), how reachable it is under
distance decay (E2SFCA), and how spatially fragmented the live fleet is at each
moment (the Wasserstein rebalancing tension), plus the observability loss from
saturation and an honest interval for an autocorrelated series.
"""

import numpy as np
import pandas as pd

import gbfs_toolkit as gb


def main() -> None:
    info, _status = gb.load_example()

    # 1. Equity of a skewed capacity distribution (40 small periphery + 10 big
    #    centre stations): Theil splits inequality into between/within-zone, Palma
    #    measures the extremes. (Needs more than a handful of stations to be meaningful.)
    rng = np.random.default_rng(0)
    caps = np.concatenate([rng.integers(2, 8, 40), rng.integers(20, 40, 10)])
    zones = ["periphery"] * 40 + ["centre"] * 10
    print("Theil decomposition:", gb.theil_index(caps, groups=zones).round(3).to_dict())
    print("Palma ratio (top10/bottom40):", round(gb.palma_ratio(caps), 2), "\n")

    # 2. Accessibility under distance decay (E2SFCA): demand points are BYOD.
    demand = pd.DataFrame(
        {"lat": [48.853, 48.857], "lon": [2.349, 2.354], "population": [1200, 800]}
    )
    access = gb.two_step_fca(info, demand, max_distance_m=800, decay="gaussian")
    print("E2SFCA accessibility per demand point:", access.round(6).to_list(), "\n")

    # 3. A synthetic 3-station, 3-timestamp panel for the dynamic metrics.
    times = pd.date_range("2026-06-01T08:00Z", periods=3, freq="5min")
    panel = pd.DataFrame(
        [
            {"station_id": s, "lat": la, "lon": lo, "fetched_at": t,
             "num_bikes_available": b, "num_docks_available": 20 - b}
            for s, la, lo in [("a", 48.85, 2.35), ("b", 48.95, 2.35), ("c", 48.85, 2.55)]
            for t, b in zip(times, {"a": [20, 10, 0], "b": [0, 5, 12], "c": [4, 6, 8]}[s], strict=True)
        ]
    )
    tension = gb.rebalancing_tension(panel)
    print("Rebalancing tension (bike-km) per timestamp:")
    print(tension.round(2).to_string(), "\n")
    print("Censored time ratio:", gb.censored_time_ratio(panel).round(3).to_dict(), "\n")

    # 4. Honest uncertainty for an autocorrelated availability series.
    series = pd.Series(np.sin(np.linspace(0, 12, 200)) * 5 + 10)
    print("Effective sample size:", round(gb.effective_sample_size(series), 1), "of 200")
    print("Block-bootstrap mean CI:", gb.block_bootstrap_ci(series, seed=42).round(2).to_dict())


if __name__ == "__main__":
    main()

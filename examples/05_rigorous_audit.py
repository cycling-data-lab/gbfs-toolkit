"""A rigorous, reproducible audit: verdict, robustness, uncertainty, hotspots.

Self-contained (uses the bundled ``load_example`` dataset and small synthetic
frames, no network), so it runs anywhere:

    python 05_rigorous_audit.py

It walks the audit the way a careful study would report it: the A1-A7 verdict and
the capacity convention, then a threshold-sensitivity sweep and a bootstrap
confidence interval to show the conclusions are not knife-edge, then spatial
hotspots with a false-discovery-rate correction.
"""

import numpy as np
import pandas as pd

import gbfs_toolkit as gb


def main() -> None:
    info, _status = gb.load_example()

    # 1. The verdict and the capacity-field convention of the (single) system.
    verdict = gb.audit_static(info)
    print("Flagged stations:", int(verdict["flagged"].sum()), "/", len(verdict))
    print("Capacity convention:", gb.capacity_convention(info).to_dict(), "\n")

    # 2. Robustness: a synthetic 25-station system that publishes 60% NaN capacity
    #    trips A7; the sweep shows the flagged set is stable across thresholds.
    synth = pd.DataFrame(
        {
            "system_id": "demo",
            "station_id": [str(i) for i in range(25)],
            "station_type": "docked_bike",
            "capacity": [np.nan] * 15 + [12.0] * 10,
            "lat": 48.85 + 0.001 * np.arange(25),
            "lon": 2.35 + 0.001 * np.arange(25),
        }
    )
    sweep = gb.audit_sensitivity(synth, {"a7_tau": [0.4, 0.5, 0.6, 0.7]}, a7_scope="all")
    a7 = sweep[sweep["class"] == "A7"]
    print("A7 robustness to its threshold (Jaccard vs baseline):")
    print(a7[["value", "systems_flagged", "jaccard_vs_baseline"]].to_string(index=False), "\n")

    # 3. Uncertainty: a cluster-bootstrap CI on the system-level flag rates (seeded).
    many = pd.concat(
        [
            synth.assign(system_id=f"s{k}", capacity=[np.nan] * (12 + k) + [10.0] * (13 - k))
            for k in range(8)
        ],
        ignore_index=True,
    )
    ci = gb.flag_rate_ci(gb.audit_static(many, a7_scope="all"), seed=42)
    print("Flag-rate 95% bootstrap CIs:")
    print(
        ci[ci["systems_flagged"] > 0][["class", "rate", "ci_lo", "ci_hi"]].to_string(index=False),
        "\n",
    )

    # 4. Spatial hotspots with FDR control (no naive per-station alpha).
    lisa = gb.local_morans_i(info, "capacity", permutations=499, seed=0, fdr=True)
    print("LISA cluster types (FDR-controlled):", lisa["cluster_type"].value_counts().to_dict())


if __name__ == "__main__":
    main()

"""Stability level of the public names (see the API policy page of the documentation).

Every name in ``gbfs_toolkit.__all__`` is **stable** unless listed here: within a major
version it keeps its signature, its documented behaviour and its results, and it is
removed only after a deprecation cycle. **Experimental** names may change, or go, in a
minor release; their docstrings carry an "Experimental" admonition, which a test checks.
"""

from __future__ import annotations

#: The flow simulator and empirical compiler (added in 2.0.0): simulated outputs with no
#: external reference yet, whose parameters and numbers are still being validated.
EXPERIMENTAL: frozenset[str] = frozenset(
    {
        "SimConfig",
        "simulate_city_flows",
        "generate_gbfs_parquet",
        "export_ml_dataset",
        "calibrate_city",
        "compute_footprint",
    }
)

#: Modules added in 2.1.0 for collecting, checking, storing and releasing data. They are
#: public (import them as ``gbfs_toolkit.<name>``) but experimental: their names,
#: parameters and output columns may change in a minor release while they are used on
#: more systems. Each carries an "Experimental" note in its docstring, which a test checks.
EXPERIMENTAL_MODULES: frozenset[str] = frozenset(
    {
        "gbfs_toolkit.collect",
        "gbfs_toolkit.history",
        "gbfs_toolkit.quality",
        "gbfs_toolkit.aggregate",
        "gbfs_toolkit.store",
        "gbfs_toolkit.stations.match",
        "gbfs_toolkit.trips",
        "gbfs_toolkit.release",
        "gbfs_toolkit.repro",
    }
)

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

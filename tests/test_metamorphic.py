"""Metamorphic tests: properties that must hold regardless of incidental input shape.

These catch the "passes on clean toy data, breaks on real feeds" class of bug:
- permutation invariance: the result must not depend on input row order (catches an
  order-dependent dedup or an unsorted diff);
- noise-column invariance: adding an unused column must not change the result (catches a
  hard-coded ``df.iloc[:, 1:]`` or positional column access).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import gbfs_toolkit as gb


def _messy_panel(seed: int) -> pd.DataFrame:
    """A deliberately messy panel: duplicates, a NaN count, unsorted, mixed stations."""
    rng = np.random.default_rng(seed)
    times = pd.to_datetime(["2026-01-01T08:00Z", "2026-01-01T08:30Z", "2026-01-01T09:00Z"])
    rows = []
    for sid, (lat, lon) in {"a": (48.85, 2.35), "b": (48.8502, 2.3503)}.items():
        for t in times:
            bikes = int(rng.integers(0, 6))
            rows.append(
                {
                    "system_id": "s",
                    "station_id": sid,
                    "lat": lat,
                    "lon": lon,
                    "fetched_at": t,
                    "num_bikes_available": bikes,
                    "num_docks_available": 10 - bikes,
                    "capacity": 10,
                }
            )
    df = pd.DataFrame(rows)
    # a duplicate (station, timestamp) and a NaN count, the messiness real feeds carry
    df = pd.concat([df, df.iloc[[0]]], ignore_index=True)
    df.loc[2, "num_bikes_available"] = np.nan
    return df


# Functions whose result must be invariant to row order. Each maps the output to a
# canonical, comparable form (sorted, index-reset).
_ORDER_INVARIANT = {
    "spatial_outage_redundancy": lambda d: (
        gb.spatial_outage_redundancy(d, radius_m=300)
        .sort_values("station_id")
        .reset_index(drop=True)
    ),
    "station_outage_rates": lambda d: (
        gb.station_outage_rates(d).sort_values("station_id").reset_index(drop=True)
    ),
    "boundary_stress": lambda d: (
        gb.boundary_stress(d).sort_values("station_id").reset_index(drop=True)
    ),
    "dynamic_gini_index": lambda d: (
        gb.dynamic_gini_index(d).sort_values("fetched_at").reset_index(drop=True)
    ),
    "censored_time_ratio": lambda d: gb.censored_time_ratio(d),
}


@pytest.mark.parametrize("name", list(_ORDER_INVARIANT))
@given(perm_seed=st.integers(min_value=0, max_value=2**32 - 1))
@settings(max_examples=15, deadline=None)
def test_permutation_invariance(name, perm_seed):
    fn = _ORDER_INVARIANT[name]
    panel = _messy_panel(seed=7)
    shuffled = panel.sample(frac=1, random_state=perm_seed % (2**31)).reset_index(drop=True)
    base = fn(panel)
    other = fn(shuffled)
    if isinstance(base, pd.Series):
        pd.testing.assert_series_equal(base, other)
    else:
        pd.testing.assert_frame_equal(base, other)


@pytest.mark.parametrize("name", list(_ORDER_INVARIANT))
def test_noise_column_invariance(name):
    fn = _ORDER_INVARIANT[name]
    panel = _messy_panel(seed=11)
    with_noise = panel.assign(_unused=np.arange(len(panel)), _label="x")
    base = fn(panel)
    other = fn(with_noise)
    # the noise column may ride along on row-preserving outputs; compare the shared columns
    if isinstance(base, pd.Series):
        pd.testing.assert_series_equal(base, other)
    else:
        shared = [c for c in base.columns if c in other.columns]
        pd.testing.assert_frame_equal(base[shared], other[shared])

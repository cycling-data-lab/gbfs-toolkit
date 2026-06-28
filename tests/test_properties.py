"""Property-based tests (Hypothesis): mathematical invariants that must hold for any input.

These catch edge cases hand-written examples miss: empty groups, all-NaN columns, ties, extreme
magnitudes. Each asserts a property of the estimator rather than a specific value.
"""

import numpy as np
import pandas as pd
from hypothesis import given, settings
from hypothesis import strategies as st

import gbfs_toolkit as gb
from gbfs_toolkit.core.utils import gini

_nonneg = st.lists(
    st.floats(min_value=0, max_value=1e6, allow_nan=False, allow_infinity=False),
    min_size=1,
    max_size=80,
)
_counts = st.integers(min_value=0, max_value=10_000)


@given(_nonneg)
def test_gini_is_bounded(values):
    g = gini(np.asarray(values))
    assert np.isnan(g) or (0.0 <= g <= 1.0)


@given(st.lists(_counts, min_size=1, max_size=60), st.lists(_counts, min_size=1, max_size=60))
def test_occupancy_is_a_probability(bikes, docks):
    n = min(len(bikes), len(docks))
    av = pd.DataFrame({"num_bikes_available": bikes[:n], "num_docks_available": docks[:n]})
    occ = gb.occupancy(av).to_numpy()
    finite = occ[~np.isnan(occ)]
    assert np.all((finite >= 0.0) & (finite <= 1.0))


@given(st.lists(st.floats(min_value=0, max_value=1e5, allow_nan=False), min_size=1, max_size=80))
def test_outage_survival_is_monotone_non_increasing(durations):
    episodes = pd.DataFrame({"duration_minutes": durations})
    surv = gb.outage_survival(episodes)["survival"].to_numpy()
    assert np.all((surv >= 0.0) & (surv <= 1.0))
    assert np.all(np.diff(surv) <= 1e-12)  # non-increasing in duration


@settings(max_examples=40, deadline=None)  # audit_static uses scipy; timing varies
@given(
    st.lists(
        st.tuples(
            st.floats(min_value=48.0, max_value=49.0, allow_nan=False),
            st.floats(min_value=2.0, max_value=3.0, allow_nan=False),
            st.integers(min_value=0, max_value=40),
        ),
        min_size=5,
        max_size=40,
    )
)
def test_audit_static_is_pure_and_deterministic(points):
    df = pd.DataFrame(
        {
            "system_id": "sys",
            "station_id": [str(i) for i in range(len(points))],
            "station_type": "docked_bike",
            "capacity": [c for _, _, c in points],
            "lat": [la for la, _, _ in points],
            "lon": [lo for _, lo, _ in points],
        }
    )
    before = df.copy(deep=True)
    v1 = gb.audit_static(df)
    v2 = gb.audit_static(df)
    pd.testing.assert_frame_equal(df, before)  # input not mutated (purity)
    pd.testing.assert_frame_equal(v1, v2)  # deterministic

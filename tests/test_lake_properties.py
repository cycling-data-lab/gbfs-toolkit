"""Property-based tests of the data-lake modules (need hypothesis, a dev dependency)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("hypothesis")

from hypothesis import given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from gbfs_toolkit.aggregate import aggregate_levels  # noqa: E402
from gbfs_toolkit.history import content_fingerprint  # noqa: E402
from gbfs_toolkit.quality import daily_coverage  # noqa: E402
from gbfs_toolkit.repro import fingerprint  # noqa: E402
from gbfs_toolkit.stations.match import match_stations  # noqa: E402
from gbfs_toolkit.trips import normalize_trips  # noqa: E402


@settings(max_examples=40, deadline=None)
@given(
    n=st.integers(min_value=1, max_value=60),
    seed=st.integers(min_value=0, max_value=10_000),
    threshold=st.floats(min_value=1, max_value=100),
)
def test_property_completeness_is_bounded_and_status_agrees_with_threshold(n, seed, threshold):
    import numpy as np

    rng = np.random.default_rng(seed)
    offsets = np.sort(rng.choice(1440, size=n, replace=False))
    t = pd.Timestamp("2026-03-01", tz="UTC") + pd.to_timedelta(offsets, unit="min")
    snaps = pd.DataFrame({"system_id": "a", "fetched_at": t})
    cov = daily_coverage(snaps, ok_threshold_pct=threshold)
    row = cov.iloc[0]
    assert row["actual_polls"] == n and 0 < row["completeness_pct"] <= 100
    assert (row["status"] == "ok") == (row["completeness_pct"] >= threshold)


@settings(max_examples=40, deadline=None)
@given(
    n=st.integers(1, 400),
    seed=st.integers(0, 10_000),
    stations=st.integers(1, 4),
)
def test_property_sum_of_n_obs_is_the_row_count_at_every_level(n, seed, stations):
    """The property checked on the research station: quarter-hour n_obs sums to the minute rows."""
    rng = np.random.default_rng(seed)
    minute = rng.integers(0, 3 * 24 * 60, size=n)
    df = pd.DataFrame(
        {
            "system_id": "a",
            "station_id": rng.integers(0, stations, size=n).astype(str),
            "fetched_at": pd.Timestamp("2026-03-01", tz="UTC")
            + pd.to_timedelta(minute, unit="min"),
            "num_bikes_available": rng.integers(0, 20, size=n),
            "num_docks_available": rng.integers(0, 20, size=n),
        }
    )
    levels = aggregate_levels(df)
    totals = {k: int(v["n_obs"].sum()) for k, v in levels.items()}
    assert set(totals.values()) == {n}
    # every coarser bucket is exactly the sum of the finer ones it contains
    fine, hourly = levels["15m"], levels["1h"]
    regrouped = (
        fine.assign(bucket_start_utc=fine["bucket_start_utc"].dt.floor("1h"))
        .groupby(["system_id", "station_id", "bucket_start_utc"])["n_obs"]
        .sum()
    )
    merged = hourly.set_index(["system_id", "station_id", "bucket_start_utc"])["n_obs"]
    pd.testing.assert_series_equal(regrouped, merged, check_names=False)
    # pct values stay in [0, 100]
    for col in ("pct_empty", "pct_full"):
        v = levels["1h"][col].dropna()
        assert ((v >= 0) & (v <= 100)).all()


@settings(max_examples=40, deadline=None)
@given(
    rows=st.lists(st.tuples(st.text(max_size=5), st.integers(-5, 5)), min_size=0, max_size=8),
    seed=st.integers(0, 99),
)
def test_property_fingerprint_does_not_depend_on_row_order(rows, seed):
    df = pd.DataFrame(rows, columns=["k", "v"])
    shuffled = df.sample(frac=1, random_state=seed)
    assert content_fingerprint(df) == content_fingerprint(shuffled)


@settings(max_examples=40, deadline=None)
@given(n_old=st.integers(0, 12), n_new=st.integers(0, 12), seed=st.integers(0, 9999))
def test_property_one_to_one_and_every_station_accounted_for(n_old, n_new, seed):
    rng = np.random.default_rng(seed)

    def table(n, prefix):
        return pd.DataFrame(
            {
                "station_id": [
                    f"{prefix}{i % 7}" if rng.random() < 0.5 else f"{i}" for i in range(n)
                ],
                "name": [f"n{rng.integers(0, 5)}" for _ in range(n)],
                "lat": 43 + rng.random(n) * 0.003,
                "lon": 3 + rng.random(n) * 0.003,
            }
        )

    old, new = table(n_old, "o"), table(n_new, "n")
    m = match_stations(old, new)
    paired = m.dropna(subset=["station_id_old", "station_id_new"])
    assert paired["station_id_old"].is_unique and paired["station_id_new"].is_unique
    assert m["station_id_old"].dropna().nunique() == old["station_id"].nunique()
    assert m["station_id_new"].dropna().nunique() == new["station_id"].nunique()
    assert set(m["match_method"]) <= {
        "same_id",
        "same_id_far",
        "same_name",
        "nearest",
        "none",
        "only_new",
    }


@settings(max_examples=30, deadline=None)
@given(
    secs=st.lists(st.integers(0, 10**7), min_size=1, max_size=10),
    durs=st.lists(st.integers(0, 7200), min_size=1, max_size=10),
)
def test_property_utc_round_trip_and_duration(secs, durs):
    n = min(len(secs), len(durs))
    start = pd.Timestamp("2025-01-01", tz="UTC") + pd.to_timedelta(secs[:n], unit="s")
    end = start + pd.to_timedelta(durs[:n], unit="s")
    raw = pd.DataFrame(
        {
            "started_at": start.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
            "ended_at": end.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
            "start_station_latitude": 1.0,
        }
    )
    out = normalize_trips(raw.assign(duration=np.nan))
    assert (out["started_at"].reset_index(drop=True) == pd.Series(start)).all()
    assert out["duration_s"].tolist() == [float(d) for d in durs[:n]]


@settings(max_examples=40, deadline=None)
@given(
    rows=st.lists(
        st.tuples(
            st.text(max_size=6), st.integers(-(10**6), 10**6), st.floats(-1e6, 1e6, allow_nan=False)
        ),
        max_size=15,
    ),
    seed=st.integers(0, 999),
)
def test_property_row_permutations_do_not_change_the_fingerprint(rows, seed):
    df = pd.DataFrame(rows, columns=["a", "b", "c"])
    assert fingerprint(df) == fingerprint(df.sample(frac=1, random_state=seed))


@settings(max_examples=30, deadline=None)
@given(values=st.lists(st.integers(0, 10**6), min_size=1, max_size=15), pos=st.integers(0, 14))
def test_property_changing_one_value_changes_the_fingerprint(values, pos):
    df = pd.DataFrame({"v": values})
    changed = df.copy()
    changed.loc[pos % len(df), "v"] += 1
    assert fingerprint(df) != fingerprint(changed)

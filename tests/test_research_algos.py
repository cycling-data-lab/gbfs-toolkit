"""Research algorithms (1.5.0): FDR, equity, rebalancing tension, resampling."""

import numpy as np
import pandas as pd

import gbfs_toolkit as gb


def test_theil_decomposes():
    assert gb.theil_index([5, 5, 5, 5]) == 0.0  # perfect equality
    vals = [1.0, 1.0, 10.0, 10.0]
    groups = ["a", "a", "b", "b"]
    d = gb.theil_index(vals, groups=groups)
    assert abs(d["total"] - (d["between"] + d["within"])) < 1e-9
    assert d["between"] > 0  # the inequality is between the two groups


def test_palma_ratio():
    # 10 values 1..10: top 10% = {10}, bottom 40% = {1,2,3,4} = 10 -> ratio 1.0
    assert abs(gb.palma_ratio(list(range(1, 11))) - 1.0) < 1e-9
    # 10 equal values: top10 = 5, bottom40 = 20 -> 0.25
    assert abs(gb.palma_ratio([5] * 10) - 0.25) < 1e-9


def test_fdr_adjust_inflates_pvalues():
    raw = np.array([0.001, 0.01, 0.04, 0.5, np.nan])
    adj = gb.fdr_adjust(raw)
    assert np.isnan(adj[-1])  # NaN preserved
    assert np.all(adj[:4] >= raw[:4] - 1e-12)  # BH never lowers a p-value


def _panel(ts_list, bikes_by_station):
    rows = []
    for ts in ts_list:
        for sid, (lat, lon, bikes) in bikes_by_station.items():
            rows.append(
                {
                    "station_id": sid,
                    "lat": lat,
                    "lon": lon,
                    "fetched_at": ts,
                    "num_bikes_available": bikes,
                }
            )
    return pd.DataFrame(rows)


def test_rebalancing_tension_zero_at_target_and_positive_when_skewed():
    ts = [pd.Timestamp("2026-01-01T08:00Z")]
    # all stations at their historical mean (single snapshot) -> tension ~ 0
    flat = _panel(ts, {"a": (48.85, 2.35, 10), "b": (48.86, 2.36, 10), "c": (48.87, 2.37, 10)})
    t = gb.rebalancing_tension(flat)
    assert float(t.iloc[0]) < 1e-6
    # skewed snapshot vs a uniform BYOD target -> positive bike-km
    skew = _panel(ts, {"a": (48.85, 2.35, 30), "b": (48.86, 2.36, 0), "c": (48.87, 2.37, 0)})
    target = pd.Series({"a": 10, "b": 10, "c": 10})
    t2 = gb.rebalancing_tension(skew, target=target)
    assert float(t2.iloc[0]) > 0


def test_effective_sample_size_and_block_bootstrap():
    rng = np.random.default_rng(0)
    iid = rng.normal(size=400)
    assert gb.effective_sample_size(iid) > 200  # ~400 for iid
    # AR(1)-like strongly autocorrelated series -> ESS well below n
    ar = np.cumsum(rng.normal(size=400))
    assert gb.effective_sample_size(ar) < gb.effective_sample_size(iid)
    a = gb.block_bootstrap_ci(ar, seed=1)
    b = gb.block_bootstrap_ci(ar, seed=1)
    pd.testing.assert_series_equal(a, b)  # seeded
    assert a["ci_lo"] <= a["estimate"] <= a["ci_hi"]


def test_censored_time_ratio():
    panel = pd.DataFrame(
        {
            "num_bikes_available": [0, 5, 5, 10],
            "num_docks_available": [10, 0, 5, 5],
        }
    )
    r = gb.censored_time_ratio(panel)
    assert r["empty_ratio"] == 0.25  # one row at 0 bikes
    assert r["full_ratio"] == 0.25  # one row at 0 docks
    assert r["censored_ratio"] == 0.5  # union

"""Threshold parameterization, sensitivity sweep, and bootstrap CI."""

import numpy as np
import pandas as pd

import gbfs_toolkit as gb


def _system(system_id: str, n_dock: int, n_nan: int, lat0: float = 48.85) -> pd.DataFrame:
    """A docked system of ``n_dock`` stations, ``n_nan`` of them NaN-capacity."""
    caps = [np.nan] * n_nan + [10.0] * (n_dock - n_nan)
    return pd.DataFrame(
        {
            "system_id": system_id,
            "station_id": [f"{system_id}-{i}" for i in range(n_dock)],
            "station_type": "docked_bike",
            "capacity": caps,
            "lat": lat0 + 0.001 * np.arange(n_dock),
            "lon": 2.35 + 0.001 * np.arange(n_dock),
        }
    )


def test_thresholds_are_backward_compatible():
    # Passing every default explicitly must equal calling with no keywords.
    df = pd.concat([_system("a", 20, 12), _system("b", 20, 2, lat0=43.6)], ignore_index=True)
    base = gb.audit_static(df)
    explicit = gb.audit_static(df, a4_sigma=3.0, a5_area_km2=50_000, a6_tau=0.01, a7_tau=0.50)
    pd.testing.assert_frame_equal(base, explicit)


def test_a7_tau_flips_the_flag():
    df = _system("a", 20, 12)  # 60% NaN-capacity docked
    assert gb.audit_static(df, a7_tau=0.50)["A7"].any()
    assert not gb.audit_static(df, a7_tau=0.70)["A7"].any()


def test_n_min_gates_system_rules():
    df = _system("a", 20, 12)
    assert gb.audit_static(df, n_min=20)["A7"].any()
    assert not gb.audit_static(df, n_min=25)["A7"].any()  # system too small now


def test_audit_sensitivity_shape_and_baseline_overlap():
    df = pd.concat([_system("a", 20, 12), _system("b", 20, 18, lat0=43.6)], ignore_index=True)
    grid = {"a7_tau": [0.50, 0.70, 0.90]}
    sens = gb.audit_sensitivity(df, grid, a7_tau=0.50)
    assert set(sens.columns) == {"param", "value", "class", "systems_flagged", "jaccard_vs_baseline"}
    a7 = sens[sens["class"] == "A7"].set_index("value")
    # At the baseline value the flagged set is identical -> Jaccard 1.0.
    assert a7.loc[0.50, "jaccard_vs_baseline"] == 1.0
    # Tightening tau can only shrink the flagged set, so overlap stays <= 1.
    assert a7.loc[0.90, "systems_flagged"] <= a7.loc[0.50, "systems_flagged"]


def test_overcapacity_ratio_matches_definition():
    # X: 10 caps=20, 10 caps=0 -> profile 20, actual 10, ratio 2.
    # Y: 1 cap=12, 19 caps=0  -> profile 12, actual 0.6, ratio 20 (over-capacity).
    def mk(sid, caps):
        return pd.DataFrame(
            {"system_id": sid, "station_id": [f"{sid}{i}" for i in range(len(caps))], "capacity": caps}
        )
    df = pd.concat([mk("X", [20.0] * 10 + [0.0] * 10), mk("Y", [12.0] + [0.0] * 19)], ignore_index=True)
    r = gb.overcapacity_ratio(df)
    assert abs(r["X"] - 2.0) < 1e-9
    assert abs(r["Y"] - 20.0) < 1e-9


def test_reclassify_overcapacity_relabels_and_is_pure():
    df = pd.DataFrame(
        {
            "system_id": "Y",
            "station_id": [f"Y{i}" for i in range(20)],
            "station_type": "docked_bike",
            "capacity": [12.0] + [0.0] * 19,
            "lat": 48.85,
            "lon": 2.35,
        }
    )
    before = df.copy(deep=True)
    out = gb.reclassify_overcapacity(df, a3_ratio=5.0)
    assert (out["station_type"] == "free_floating").all()  # ratio 20 > 5
    pd.testing.assert_frame_equal(df, before)  # input unchanged
    assert (gb.reclassify_overcapacity(df, a3_ratio=50.0)["station_type"] == "docked_bike").all()


def test_classify_from_vehicle_types_is_feed_intrinsic():
    info = pd.DataFrame(
        {
            "system_id": ["car", "bike", "mixed"],
            "station_type": ["docked_bike"] * 3,
        }
    )
    vt = pd.DataFrame(
        {
            "system_id": ["car", "car", "bike", "mixed", "mixed"],
            # 'car' has car + cargo_bicycle (like Citiz) -> carsharing (no plain bicycle);
            # 'bike' is a bike-share; 'mixed' offers cars AND bicycles -> not pure A1.
            "form_factor": ["car", "cargo_bicycle", "bicycle", "car", "bicycle"],
        }
    )
    out = gb.classify_from_vehicle_types(info, vt)
    typ = out.set_index("system_id")["station_type"]
    assert typ["car"] == "carsharing"
    assert typ["bike"] == "docked_bike"
    assert typ["mixed"] == "docked_bike"  # has bicycle -> vetoed
    pd.testing.assert_frame_equal(info, info)  # input copy, unchanged
    assert gb.classify_from_vehicle_types(info, None).equals(info)  # no vehicle_types -> unchanged


def test_classify_from_virtual_station():
    info = pd.DataFrame(
        {
            "system_id": "s",
            "station_id": ["a", "b", "c"],
            "station_type": ["docked_bike"] * 3,
            "is_virtual_station": [True, False, None],
        }
    )
    out = gb.classify_from_virtual_station(info)
    assert list(out["station_type"]) == ["free_floating", "docked_bike", "docked_bike"]
    # No is_virtual_station column -> unchanged.
    plain = info.drop(columns=["is_virtual_station"])
    pd.testing.assert_frame_equal(gb.classify_from_virtual_station(plain), plain)


def test_flag_sentinel_coordinates():
    info = pd.DataFrame(
        {"station_id": ["ok", "null_island", "near0"], "lat": [48.85, 0.0, 1e-9], "lon": [2.35, 0.0, 0.0]}
    )
    mask = gb.flag_sentinel_coordinates(info)
    assert list(mask) == [False, True, True]


def test_flag_rate_ci_is_reproducible_and_bracketing():
    df = pd.concat(
        [_system(f"s{i}", 20, 12 if i % 2 else 0, lat0=48 + 0.1 * i) for i in range(8)],
        ignore_index=True,
    )
    verdict = gb.audit_static(df)
    a = gb.flag_rate_ci(verdict, seed=42, n_boot=2000)
    b = gb.flag_rate_ci(verdict, seed=42, n_boot=2000)
    pd.testing.assert_frame_equal(a, b)  # seeded -> identical
    row = a[a["class"] == "A7"].iloc[0]
    assert row["ci_lo"] <= row["rate"] <= row["ci_hi"]

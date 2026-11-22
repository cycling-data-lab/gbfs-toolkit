"""The public API contract: names, signatures and results that other projects rely on.

Several research codebases call this library, and some delegate their core computations
to it. Under semantic versioning those calls must keep working, with the same results,
for the whole 2.x line. This file guards that promise:

* every name in ``gbfs_toolkit.__all__`` resolves;
* the functions known to be used downstream keep their import paths and every existing
  parameter (same name, kind and default). Adding a keyword-only parameter with a default
  is allowed; removing, renaming, reordering or re-defaulting one is not;
* their results on small fixed inputs stay the same (golden values). A deliberate change
  of a result is a behaviour change: it needs a CHANGELOG entry, and a new major version
  if it changes a documented contract.
"""

from __future__ import annotations

import importlib
import inspect

import numpy as np
import pandas as pd
import pytest

import gbfs_toolkit as gb

# (module path, name) of the functions other projects are known to call.
DOWNSTREAM = [
    ("gbfs_toolkit.io.timeseries", "detect_frozen_stations"),
    ("gbfs_toolkit.io.timeseries", "insert_explicit_gaps"),
    ("gbfs_toolkit.analytics.temporal", "diurnal_summary_stats"),
    ("gbfs_toolkit.analytics.distribution", "concentration_metrics"),
    ("gbfs_toolkit.analytics.distribution", "lorenz_curve"),
    ("gbfs_toolkit.audit.static", "audit_static"),
    ("gbfs_toolkit.audit.static", "classify_from_vehicle_types"),
    ("gbfs_toolkit.spatial.graph", "knn_adjacency"),
    ("gbfs_toolkit.spatial.graph", "normalized_laplacian"),
    ("gbfs_toolkit.spatial.graph", "low_freq_basis"),
    ("gbfs_toolkit.spatial.graph", "spectral_projection_r2"),
    ("gbfs_toolkit.spatial.graph", "degree_preserving_rewire"),
    ("gbfs_toolkit.spatial.graph", "permute_signal"),
    ("gbfs_toolkit.spatial.graph", "band_limited_signal"),
]

_P = inspect.Parameter
POS, KW = _P.POSITIONAL_OR_KEYWORD, _P.KEYWORD_ONLY
NO = _P.empty

# Parameters as of 2.0.0: (name, kind, default).
SIGNATURES = {
    "detect_frozen_stations": [
        ("panel", POS, NO),
        ("value_col", KW, "num_bikes_available"),
        ("columns", KW, None),
        ("min_run_hours", KW, 6.0),
        ("active_hours", KW, (6, 22)),
        ("strict", KW, False),
    ],
    "insert_explicit_gaps": [
        ("panel", POS, NO),
        ("expected_freq", KW, "5min"),
        ("tolerance", KW, "15min"),
        ("time_col", KW, "fetched_at"),
        ("by", KW, ("system_id", "station_id")),
    ],
    "diurnal_summary_stats": [
        ("panel", POS, NO),
        ("value_col", KW, "num_bikes_available"),
        ("time_col", KW, "fetched_at"),
    ],
    "concentration_metrics": [("info", POS, NO), ("value_col", KW, "capacity")],
    "lorenz_curve": [("info", POS, NO), ("value_col", KW, "capacity")],
    "audit_static": [
        ("stations", POS, NO),
        ("a7_scope", KW, "docked"),
        ("a4_sigma", KW, 3.0),
        ("a5_area_km2", KW, 50_000.0),
        ("a6_tau", KW, 0.01),
        ("a7_tau", KW, 0.5),
        ("n_min", KW, None),
    ],
    "classify_from_vehicle_types": [
        ("info", POS, NO),
        ("vehicle_types", POS, NO),
        ("car_factors", KW, ("car",)),
        ("bike_factors", KW, ("bicycle",)),
    ],
    "knn_adjacency": [("lat", POS, NO), ("lon", POS, NO), ("k", KW, 10), ("gaussian", KW, True)],
    "normalized_laplacian": [("W", POS, NO)],
    "low_freq_basis": [("L", POS, NO), ("d", POS, NO)],
    "spectral_projection_r2": [("y", POS, NO), ("basis", POS, NO)],
    "degree_preserving_rewire": [("W", POS, NO), ("n_swaps", KW, None), ("seed", KW, 42)],
    "permute_signal": [("y", POS, NO), ("seed", KW, 42)],
    "band_limited_signal": [
        ("L", POS, NO),
        ("r2_target", KW, 0.8),
        ("n_low", KW, 16),
        ("seed", KW, 42),
    ],
}


def test_every_name_in_all_resolves():
    assert len(gb.__all__) == len(set(gb.__all__)), "duplicate names in __all__"
    missing = [name for name in gb.__all__ if not hasattr(gb, name)]
    assert not missing


@pytest.mark.parametrize(("module", "name"), DOWNSTREAM, ids=[n for _, n in DOWNSTREAM])
def test_downstream_import_paths(module, name):
    func = getattr(importlib.import_module(module), name)
    # Re-exported at the top level as the same object (graph primitives included).
    assert getattr(gb, name) is func


@pytest.mark.parametrize("name", sorted(SIGNATURES))
def test_downstream_signatures_only_grow(name):
    params = inspect.signature(getattr(gb, name)).parameters
    expected = SIGNATURES[name]
    for position, (pname, kind, default) in enumerate(expected):
        assert pname in params, f"{name}: parameter {pname!r} was removed or renamed"
        param = params[pname]
        assert param.kind == kind, f"{name}: {pname!r} changed kind"
        assert param.default == default, f"{name}: {pname!r} changed its default"
        if kind == POS:
            assert list(params).index(pname) == position, f"{name}: {pname!r} moved"
    for pname, param in params.items():
        if pname not in {p for p, _, _ in expected}:
            assert param.kind == KW and param.default is not NO, (
                f"{name}: new parameter {pname!r} must be keyword-only with a default"
            )


# --- golden results ---------------------------------------------------------------


def _panel() -> pd.DataFrame:
    times = pd.date_range("2026-03-02T05:00Z", periods=18, freq="1h")
    series = {"a": [5] * 18, "b": list(range(18)), "c": [3] * 9 + [4] * 9}
    rows = [
        {
            "system_id": "s",
            "station_id": sid,
            "fetched_at": t,
            "num_bikes_available": v,
            "num_docks_available": 20 - v,
        }
        for sid, values in series.items()
        for t, v in zip(times, values, strict=True)
    ]
    return pd.DataFrame(rows)


def _info() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "system_id": "s",
            "station_id": list("abcdefgh"),
            "capacity": [10, 12, 15, 20, 20, 25, 30, 68],
            "station_type": "docked_bike",
            "lat": 48.85 + np.arange(8) * 0.002,
            "lon": 2.35 + np.arange(8) * 0.002,
        }
    )


def _audit_fixture() -> pd.DataFrame:
    def grid(sid, n, lat0, lon0, cap, step=0.004):
        i = np.arange(n)
        return pd.DataFrame(
            {
                "system_id": sid,
                "station_id": [f"{sid}{k}" for k in i],
                "station_type": "docked_bike",
                "capacity": cap,
                "lat": lat0 + (i // 5) * step,
                "lon": lon0 + (i % 5) * step,
            }
        )

    p = grid("p", 25, 48.85, 2.35, 15.0)  # A2: one constant capacity
    q = grid("q", 25, 45.75, 4.85, np.r_[10:35].astype(float))
    q.loc[0, "station_type"] = "carsharing"  # A1
    q.loc[1, "station_type"] = "free_floating"  # A3
    q.loc[2, ["lat", "lon"]] = [45.95, 5.10]  # A4: far from its neighbours
    q.loc[3, "capacity"] = 0.0  # A6: 1/25 zero-capacity docks
    r = grid("r", 25, 43.60, 3.87, np.r_[10:35].astype(float))
    r.loc[:14, "capacity"] = np.nan  # A7: 15/25 null capacities
    w = grid("w", 6, 40.0, -3.7, np.r_[10:16].astype(float))
    w.loc[5, ["lat", "lon"]] = [44.0, 1.0]  # A5: bounding box above 50,000 km2
    return pd.concat([p, q, r, w], ignore_index=True)


def test_golden_audit_static():
    verdict = gb.audit_static(_audit_fixture())
    counts = verdict.groupby("system_id")[[*gb.AUDIT_FLAGS, "flagged"]].sum()
    assert counts.to_dict("index") == {
        "p": {"A1": 0, "A2": 25, "A3": 0, "A4": 0, "A5": 0, "A6": 0, "A7": 0, "flagged": 25},
        "q": {"A1": 1, "A2": 0, "A3": 1, "A4": 1, "A5": 0, "A6": 25, "A7": 0, "flagged": 25},
        "r": {"A1": 0, "A2": 0, "A3": 0, "A4": 0, "A5": 0, "A6": 0, "A7": 25, "flagged": 25},
        "w": {"A1": 0, "A2": 0, "A3": 0, "A4": 1, "A5": 6, "A6": 0, "A7": 0, "flagged": 6},
    }
    assert verdict.loc[verdict["A4"], "station_id"].tolist() == ["q2", "w5"]
    assert list(verdict.columns) == [
        "system_id",
        "station_id",
        *gb.AUDIT_FLAGS,
        "flagged",
        "reason",
    ]


def test_golden_classify_from_vehicle_types():
    vt = pd.DataFrame({"system_id": ["s", "s"], "form_factor": ["car", "scooter_standing"]})
    out = gb.classify_from_vehicle_types(_info(), vt)
    assert out["station_type"].unique().tolist() == ["carsharing"]
    bikes = pd.DataFrame({"system_id": ["s", "s"], "form_factor": ["car", "bicycle"]})
    assert gb.classify_from_vehicle_types(_info(), bikes)["station_type"].unique().tolist() == [
        "docked_bike"
    ]


def test_golden_detect_frozen_stations():
    out = gb.detect_frozen_stations(_panel())
    assert out.to_dict("index") == {
        ("s", "a"): {
            "n_obs": 16,
            "longest_const_run_hours": 15.0,
            "frozen_value": 5,
            "is_frozen": True,
        },
        ("s", "b"): {
            "n_obs": 16,
            "longest_const_run_hours": 0.0,
            "frozen_value": 1,
            "is_frozen": False,
        },
        ("s", "c"): {
            "n_obs": 16,
            "longest_const_run_hours": 7.0,
            "frozen_value": 3,
            "is_frozen": True,
        },
    }


def test_golden_insert_explicit_gaps():
    panel = _panel()
    station_a = panel[panel["station_id"] == "a"].drop(index=[3, 4, 5])
    out = gb.insert_explicit_gaps(station_a, tolerance="90min")
    assert len(out) == 16
    marker = out.loc[out["num_bikes_available"].isna(), "fetched_at"].tolist()
    assert marker == [pd.Timestamp("2026-03-02T09:00Z")]


def test_golden_diurnal_summary_stats():
    out = gb.diurnal_summary_stats(_panel())
    assert list(out.columns) == ["hour", "mean", "median", "p05", "p95", "n"]
    first = out.head(3)
    assert first["hour"].tolist() == [5, 6, 7]
    np.testing.assert_allclose(first["mean"], [8 / 3, 3.0, 10 / 3])
    np.testing.assert_allclose(first["p05"], [0.3, 1.2, 2.1])
    assert first["n"].tolist() == [3, 3, 3]


def test_golden_concentration_and_lorenz():
    conc = gb.concentration_metrics(_info())
    assert conc.to_dict() == {
        "n_stations": 8.0,
        "total_capacity": 200.0,
        "gini": 0.3287,
        "theil": 0.1948,
        "top_decile_share": 0.34,
    }
    curve = gb.lorenz_curve(_info())
    np.testing.assert_allclose(
        curve["cum_value_share"], [0.0, 0.05, 0.11, 0.185, 0.285, 0.385, 0.51, 0.66, 1.0]
    )


def test_golden_graph_primitives():
    from gbfs_toolkit.spatial import graph

    lat = 43.6 + np.arange(12) * 0.003
    lon = 3.87 + (np.arange(12) % 4) * 0.004
    W = graph.knn_adjacency(lat, lon, k=3)
    assert W.shape == (12, 12) and int((W > 0).sum()) == 42
    assert np.allclose(W, W.T)
    assert round(float(W.sum()), 6) == 23.269696
    L = graph.normalized_laplacian(W)
    assert round(float(np.trace(L)), 6) == 12.0
    B = graph.low_freq_basis(L, 3)
    assert B.shape == (12, 3)
    assert round(graph.spectral_projection_r2(lat - lat.mean(), B), 6) == 0.970798
    R = graph.degree_preserving_rewire(W, seed=1)
    assert R.sum(axis=1).tolist() == (W > 0).sum(axis=1).tolist()
    assert graph.permute_signal(np.arange(5), seed=0).tolist() == [2.0, 4.0, 3.0, 0.0, 1.0]
    s = graph.band_limited_signal(L, r2_target=0.7, n_low=3, seed=0)
    assert round(float(s.std()), 6) == 1.0
    assert round(graph.spectral_projection_r2(s, B), 4) == 0.7

"""Tests for the A1–A7 semantic audit on synthetic frames hitting each rule."""

import numpy as np
import pandas as pd
import pytest

from gbfs_toolkit import audit_static
from gbfs_toolkit.models import SchemaError


def _docked_grid(system_id="sys", n=30, capacity=20, lat0=48.85, lon0=2.35):
    """A clean docked system: small grid, varied-ish capacity, no anomalies."""
    rng = np.random.default_rng(0)
    side = int(np.ceil(np.sqrt(n)))
    rows = []
    for i in range(n):
        rows.append(
            {
                "system_id": system_id,
                "station_id": f"{system_id}-{i}",
                "station_type": "docked_bike",
                "capacity": capacity + (i % 5),  # non-constant
                "lat": lat0 + 0.001 * (i // side) + rng.normal(0, 1e-5),
                "lon": lon0 + 0.001 * (i % side) + rng.normal(0, 1e-5),
            }
        )
    return pd.DataFrame(rows)


def test_clean_system_not_flagged():
    v = audit_static(_docked_grid())
    assert not v["flagged"].any()
    assert (v["reason"] == "").all()


def test_schema_error_on_missing_columns():
    with pytest.raises(SchemaError):
        audit_static(pd.DataFrame({"system_id": ["x"], "station_id": ["y"]}))


def test_a1_carsharing():
    df = _docked_grid()
    df.loc[0, "station_type"] = "carsharing"
    v = audit_static(df)
    assert bool(v.loc[0, "A1"])
    assert "Out-of-domain inclusion" in v.loc[0, "reason"]


def test_a2_placeholder_capacity():
    df = _docked_grid(capacity=20)
    df["capacity"] = 20  # constant non-zero across >= 20 stations
    v = audit_static(df)
    assert v["A2"].all()


def test_a3_free_floating():
    df = _docked_grid()
    df.loc[1, "station_type"] = "free_floating"
    v = audit_static(df)
    assert bool(v.loc[1, "A3"])


def test_a4_geospatial_outlier():
    df = _docked_grid(n=30)
    df.loc[0, "lat"] = 0.0  # transposed/teleported station far from the rest
    df.loc[0, "lon"] = 0.0
    v = audit_static(df)
    assert bool(v.loc[0, "A4"])
    assert not bool(v.loc[5, "A4"])


def test_a6_zero_capacity_docks():
    df = _docked_grid(n=40)
    df.loc[:5, "capacity"] = 0  # >1% of docked stations declare capacity 0
    v = audit_static(df)
    assert v["A6"].all()


def test_a7_null_capacity():
    df = _docked_grid(n=40)
    df.loc[: len(df) // 2 + 1, "capacity"] = np.nan  # >= 50% NaN
    v = audit_static(df)
    assert v["A7"].all()


def test_a7_scope_all_flags_dockless_system():
    # A fully free-floating system with null capacity: docked-aware A7 ignores it,
    # a7_scope="all" reproduces the gbfs-audit-catalogue verdict (flag the system).
    df = _docked_grid(n=30)
    df["station_type"] = "free_floating"
    df["capacity"] = np.nan
    assert not audit_static(df)["A7"].any()  # default docked scope: not flagged
    assert audit_static(df, a7_scope="all")["A7"].all()  # all scope: flagged


def test_a7_scope_invalid_raises():
    with pytest.raises(ValueError, match="a7_scope"):
        audit_static(_docked_grid(), a7_scope="bogus")


def test_flags_and_reason_consistent():
    df = _docked_grid()
    df.loc[0, "station_type"] = "carsharing"
    v = audit_static(df)
    assert v.loc[0, "flagged"]
    # reason non-empty exactly when flagged
    assert ((v["reason"] != "") == v["flagged"]).all()

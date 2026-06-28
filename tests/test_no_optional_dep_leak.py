"""Core functions must not borrow an optional / transitive dependency.

Setting a module to ``None`` in ``sys.modules`` makes any fresh ``import`` of it raise
``ImportError``. We do that for the optional extras and then run the core paths: if a
"core" function secretly needs jinja2 (the v1.6.0 to_latex bug), geopandas, sklearn or
pyarrow, the test fails here instead of in a minimal user install.
"""

from __future__ import annotations

import sys

import pandas as pd
import pytest

import gbfs_toolkit as gb

_OPTIONAL = ("jinja2", "geopandas", "sklearn", "pyarrow", "tabulate", "requests")


@pytest.fixture
def no_optional_deps(monkeypatch):
    for mod in _OPTIONAL:
        monkeypatch.setitem(sys.modules, mod, None)
    yield


def test_format_paper_summary_needs_no_jinja2(no_optional_deps):
    prof = pd.Series({"n_stations": 100, "mean_occupancy": 0.4123})
    assert "0.41" in gb.format_paper_summary(prof, fmt="markdown")
    assert "tabular" in gb.format_paper_summary(prof.to_frame("value"), fmt="latex")


def test_core_audit_and_analytics_need_no_extras(no_optional_deps):
    stations = pd.DataFrame(
        {
            "system_id": "s",
            "station_id": ["a", "b"],
            "station_type": ["docked_bike", "carsharing"],
            "capacity": [20, 5],
            "lat": [48.85, 48.86],
            "lon": [2.35, 2.36],
        }
    )
    assert "flagged" in gb.audit_static(stations).columns
    assert "gini" in gb.concentration_metrics(stations).index

    panel = pd.DataFrame(
        {
            "system_id": "s",
            "station_id": ["a", "b", "a", "b"],
            "lat": [48.85, 48.86, 48.85, 48.86],
            "lon": [2.35, 2.36, 2.35, 2.36],
            "fetched_at": pd.to_datetime(
                ["2026-01-01T08:00Z", "2026-01-01T08:00Z", "2026-01-01T09:00Z", "2026-01-01T09:00Z"]
            ),
            "num_bikes_available": [0, 5, 3, 0],
            "num_docks_available": [10, 5, 7, 10],
        }
    )
    # scipy is a core dep, so these spatial/panel functions must work with no extras.
    assert "systemic_outage_ratio" in gb.spatial_outage_redundancy(panel).columns
    assert "pickup_stress_ratio" in gb.boundary_stress(panel).columns
    assert "morans_i" in gb.morans_i(stations, "capacity", k=1).index

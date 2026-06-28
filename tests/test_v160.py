"""Tests for the v1.6.0 additions: feed governance, service stress, panel ergonomics."""

from __future__ import annotations

import pandas as pd
import pytest

import gbfs_toolkit as gb


def _status_panel() -> pd.DataFrame:
    times = pd.to_datetime(["2026-01-01T08:00Z", "2026-01-01T09:00Z", "2026-01-01T10:00Z"])
    rows = []
    for sid in ("a", "b"):
        for t, bikes, docks in zip(times, [0, 1, 5], [10, 9, 5], strict=True):
            rows.append(
                {
                    "system_id": "s",
                    "station_id": sid,
                    "fetched_at": t,
                    "num_bikes_available": bikes,
                    "num_docks_available": docks,
                    "lat": 48.85 if sid == "a" else 48.8501,
                    "lon": 2.35 if sid == "a" else 2.3501,
                    "capacity": 20,
                }
            )
    return pd.DataFrame(rows)


# --- vehicle_id_persistence -------------------------------------------------


def test_vehicle_id_persistence_rotating_vs_persistent():
    times = pd.to_datetime(["2026-01-01T00:00Z", "2026-01-01T01:00Z"])
    rotating = pd.DataFrame(
        {
            "vehicle_id": ["a0", "a1", "b0", "b1"],
            "fetched_at": [*([times[0]] * 2), *([times[1]] * 2)],
        }
    )
    persistent = pd.DataFrame(
        {
            "vehicle_id": ["a0", "a1", "a0", "a1"],
            "fetched_at": [*([times[0]] * 2), *([times[1]] * 2)],
        }
    )
    rot = gb.vehicle_id_persistence(rotating, lags=("1h",))
    per = gb.vehicle_id_persistence(persistent, lags=("1h",))
    assert float(rot["jaccard_1h"].iloc[0]) == 0.0
    assert float(per["jaccard_1h"].iloc[0]) == 1.0
    assert int(per["n_unique_ids"].iloc[0]) == 2
    # persistent ids live the full hour; rotating ids appear once (zero span)
    assert float(per["median_lifespan_h"].iloc[0]) == 1.0
    assert float(rot["median_lifespan_h"].iloc[0]) == 0.0


def test_vehicle_id_persistence_requires_columns():
    with pytest.raises(gb.SchemaError):
        gb.vehicle_id_persistence(pd.DataFrame({"x": [1]}))


# --- boundary_stress --------------------------------------------------------


def test_boundary_stress_absolute_thresholds():
    out = gb.boundary_stress(_status_panel()).set_index("station_id")
    # bikes <= 2 at 2 of 3 obs
    assert float(out.loc["a", "pickup_stress_ratio"]) == pytest.approx(2 / 3)
    assert int(out.loc["a", "n_obs"]) == 3


def test_boundary_stress_virtual_is_na():
    panel = pd.DataFrame(
        {
            "system_id": "s",
            "station_id": "v",
            "num_bikes_available": [0, 0],
            "num_docks_available": [0, 0],
            "capacity": [0, 0],
        }
    )
    out = gb.boundary_stress(panel)
    assert pd.isna(out["dropoff_stress_ratio"].iloc[0])
    assert float(out["pickup_stress_ratio"].iloc[0]) == 1.0


# --- spatial_outage_redundancy ----------------------------------------------


def test_spatial_outage_redundancy_local_vs_systemic():
    panel = _status_panel().copy()
    # force a fully-empty neighbourhood at the last timestamp
    panel.loc[panel["fetched_at"] == panel["fetched_at"].max(), "num_bikes_available"] = 0
    out = gb.spatial_outage_redundancy(panel, radius_m=300).set_index("station_id")
    assert int(out.loc["a", "n_neighbors"]) == 1
    assert (
        0.0
        <= float(out.loc["a", "systemic_outage_ratio"])
        <= float(out.loc["a", "local_outage_ratio"])
    )


# --- coverage_report system level -------------------------------------------


def test_coverage_report_system_level():
    out = gb.coverage_report(_status_panel(), level="system")
    assert out.index.name == "system_id"
    assert int(out["n_stations"].iloc[0]) == 2
    assert int(out["total_snapshots"].iloc[0]) == 3
    assert out["median_cadence_s"].iloc[0] == pytest.approx(3600.0)


def test_coverage_report_bad_level():
    with pytest.raises(ValueError, match="level"):
        gb.coverage_report(_status_panel(), level="nope")


# --- panel ergonomics -------------------------------------------------------


def test_add_local_time():
    out = gb.add_local_time(_status_panel(), "Europe/Paris")
    assert "local_time" in out.columns
    assert int(out["local_time"].dt.hour.iloc[0]) == 9  # 08:00 UTC -> 09:00 CET


def test_resample_panel_ffill_step():
    panel = pd.DataFrame(
        {
            "station_id": "a",
            "fetched_at": pd.to_datetime(["2026-01-01T00:00Z", "2026-01-01T00:30Z"]),
            "num_bikes_available": [5, 8],
        }
    )
    out = gb.resample_panel(panel, "15min")
    assert out["num_bikes_available"].tolist() == [5, 5, 8]
    assert len(out) == 3


def test_insert_explicit_gaps_marks_outage():
    panel = pd.DataFrame(
        {
            "station_id": "a",
            "fetched_at": pd.to_datetime(
                ["2026-01-01T00:00Z", "2026-01-01T00:05Z", "2026-01-01T02:00Z"]
            ),
            "num_bikes_available": [5, 4, 6],
        }
    )
    out = gb.insert_explicit_gaps(panel)
    assert len(out) == 4
    assert int(out["num_bikes_available"].isna().sum()) == 1


def test_extract_snapshot_asof():
    panel = pd.DataFrame(
        {
            "station_id": ["a", "a", "b"],
            "fetched_at": pd.to_datetime(
                ["2026-01-01T07:59Z", "2026-01-01T08:30Z", "2026-01-01T08:00Z"]
            ),
            "num_bikes_available": [3, 9, 7],
        }
    )
    snap = gb.extract_snapshot_asof(panel, "2026-01-01T08:00Z").set_index("station_id")
    assert int(snap.loc["a", "num_bikes_available"]) == 3
    assert int(snap.loc["b", "num_bikes_available"]) == 7
    # nothing within tolerance -> empty
    assert gb.extract_snapshot_asof(panel, "2020-01-01T00:00Z").empty


def test_to_wide_matrix_shape():
    wide = gb.to_wide_matrix(_status_panel())
    assert wide.shape == (3, 2)
    assert list(wide.columns) == ["a", "b"]


# --- spatial / presentation helpers -----------------------------------------


def test_filter_by_bbox():
    df = pd.DataFrame({"station_id": ["a", "b"], "lat": [48.85, 40.0], "lon": [2.35, -3.0]})
    kept = gb.filter_by_bbox(df, (2.0, 48.0, 3.0, 49.0))
    assert kept["station_id"].tolist() == ["a"]


def test_format_paper_summary_markdown_and_latex():
    prof = pd.Series({"n_stations": 100, "mean_occupancy": 0.4123})
    md = gb.format_paper_summary(prof)
    assert "mean_occupancy" in md and "0.41" in md
    tex = gb.format_paper_summary(prof.to_frame("value"), fmt="latex")
    assert "tabular" in tex
    with pytest.raises(ValueError, match="fmt"):
        gb.format_paper_summary(prof, fmt="html")


def test_new_public_api_is_exported():
    for name in (
        "vehicle_id_persistence",
        "boundary_stress",
        "spatial_outage_redundancy",
        "format_paper_summary",
        "add_local_time",
        "resample_panel",
        "insert_explicit_gaps",
        "extract_snapshot_asof",
        "to_wide_matrix",
        "filter_by_bbox",
    ):
        assert name in gb.__all__
        assert callable(getattr(gb, name))

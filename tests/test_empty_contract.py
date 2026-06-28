"""Empty-input contract: descriptive functions return an empty typed frame, never crash.

A pandas-style guarantee for method chaining and degraded GBFS feeds: a filtered panel with
no rows left must not raise; it must return an empty DataFrame/Series with the right shape.
"""

import pandas as pd
import pytest

import gbfs_toolkit as gb


def _empty_panel() -> pd.DataFrame:
    cols = [
        "num_bikes_available",
        "num_docks_available",
        "lat",
        "lon",
        "capacity",
    ]
    df = pd.DataFrame({c: pd.Series(dtype="float64") for c in cols})
    df["system_id"] = pd.Series(dtype="string")
    df["station_id"] = pd.Series(dtype="string")
    df["fetched_at"] = pd.to_datetime(pd.Series(dtype="float64"), utc=True)
    df["last_reported"] = df["fetched_at"]
    return df


def _empty_info() -> pd.DataFrame:
    info = _empty_panel()[["system_id", "station_id", "lat", "lon", "capacity"]].copy()
    info["occ"] = pd.Series(dtype="float64")
    return info


_PANEL_FUNCS = [
    "occupancy",
    "station_state",
    "dynamic_gini_index",
    "spatial_center_of_mass",
    "service_reliability_index",
    "station_outage_rates",
    "docking_pressure",
    "cumulative_imbalance",
    "flow_asymmetry_ratio",
    "fleet_turnover_proxy",
    "aliasing_vulnerability",
    "temporal_autocorrelation",
    "temporal_concentration",
    "diurnal_summary_stats",
    "diurnal_bimodality",
    "availability_synchrony",
    "availability_stats",
    "temporal_context_features",
    "turnover",
    "flow_balance",
    "calculate_net_flow",
    "coverage_report",
    "stockout_episodes",
]


@pytest.mark.parametrize("name", _PANEL_FUNCS)
def test_panel_functions_accept_empty(name):
    out = getattr(gb, name)(_empty_panel())
    assert isinstance(out, (pd.DataFrame, pd.Series))
    assert len(out) == 0


_INFO_FUNCS = ["concentration_metrics", "lorenz_curve", "coverage_stats"]


@pytest.mark.parametrize("name", _INFO_FUNCS)
def test_info_functions_accept_empty(name):
    out = getattr(gb, name)(_empty_info())
    assert isinstance(out, (pd.DataFrame, pd.Series))


def test_summary_functions_accept_empty():
    # system_profile returns a one-row profile Series, not an empty frame
    prof = gb.system_profile(_empty_panel())
    assert isinstance(prof, pd.Series) and prof["n_stations"] == 0
    rk = gb.ripley_k(_empty_info(), radii=[100.0])
    assert isinstance(rk, pd.DataFrame) and rk["k"].isna().all()


def test_spatial_and_two_frame_functions_accept_empty():
    info = _empty_info()
    assert isinstance(gb.morans_i(info, "occ"), pd.Series)
    assert isinstance(gb.local_morans_i(info, "occ", permutations=9), pd.DataFrame)
    assert isinstance(gb.capacity_utilization(_empty_panel(), info), pd.DataFrame)
    veh = pd.DataFrame(
        {
            "system_id": pd.Series(dtype="string"),
            "vehicle_id": pd.Series(dtype="string"),
            "lat": pd.Series(dtype="float64"),
            "lon": pd.Series(dtype="float64"),
            "fetched_at": pd.to_datetime(pd.Series(dtype="float64"), utc=True),
        }
    )
    assert isinstance(gb.spatial_entropy(veh), pd.DataFrame)
    assert isinstance(gb.vehicle_idle_time(veh), pd.DataFrame)
    assert isinstance(
        gb.outage_survival(pd.DataFrame({"duration_minutes": pd.Series(dtype="float64")})),
        pd.DataFrame,
    )

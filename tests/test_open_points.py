"""The seven open points of 2.0.1, each with an opt-in correction (2.1.0).

For each: the default still gives the historical result, the option gives the corrected one, a
call that leaves the option unset on an input where they differ emits a ``FutureWarning`` that
announces 3.0 (and none when they agree, or when the option is given either way).
"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
import pytest

import gbfs_toolkit as gb
from gbfs_toolkit.analytics.frames import STATION_STATES, STATION_STATES_WITH_UNKNOWN


def announces(record) -> list[str]:
    return [str(w.message) for w in record if issubclass(w.category, FutureWarning)]


def quiet(fn, *args, **kw):
    """Call ``fn`` and fail on any FutureWarning."""
    with warnings.catch_warnings():
        warnings.simplefilter("error", FutureWarning)
        return fn(*args, **kw)


def gappy_panel(dtype: str) -> pd.DataFrame:
    """Four rows of one station, one with a missing bike count and a missing dock count."""
    bikes = pd.Series([0, 1, 5, 0], dtype="float64")
    docks = pd.Series([4, 3, 0, 2], dtype="float64")
    bikes[1] = docks[3] = np.nan
    if dtype == "Int64":
        bikes, docks = bikes.astype("Int64"), docks.astype("Int64")
    return pd.DataFrame(
        {
            "system_id": "s",
            "station_id": "a",
            "fetched_at": pd.date_range("2026-03-02T08:00Z", periods=4, freq="1h"),
            "num_bikes_available": bikes,
            "num_docks_available": docks,
        }
    )


# --- 5. rates over the rows that have a count -----------------------------------------------

RATES = [
    ("station_outage_rates", ["stockout_rate", "saturation_rate"]),
    ("boundary_stress", ["pickup_stress_ratio", "dropoff_stress_ratio"]),
    ("service_reliability_index", ["prob_bikes_avail", "prob_docks_avail", "prob_full_service"]),
]


@pytest.mark.parametrize(("name", "columns"), RATES)
def test_rates_default_is_historical_and_announces_the_change(name, columns):
    fn = getattr(gb, name)
    panel = gappy_panel("float64")
    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        default = fn(panel)
    messages = announces(record)
    assert len(messages) == 1 and "3.0" in messages[0] and "valid_only" in messages[0]
    pd.testing.assert_frame_equal(default, quiet(fn, panel, valid_only=False))


@pytest.mark.parametrize(("name", "columns"), RATES)
def test_valid_only_gives_the_same_rate_for_float_and_nullable_integer_columns(name, columns):
    fn = getattr(gb, name)
    as_float, as_int = gappy_panel("float64"), gappy_panel("Int64")
    corrected = quiet(fn, as_float, valid_only=True)
    pd.testing.assert_frame_equal(corrected, quiet(fn, as_int, valid_only=True))
    # the historical rule disagrees with itself on the same data (the reason for the option)
    legacy_float = quiet(fn, as_float, valid_only=False)
    legacy_int = quiet(fn, as_int, valid_only=False)
    assert not legacy_float[columns].equals(legacy_int[columns])
    # and on a nullable integer column the historical rule already is the corrected one (except
    # a joint rate, where a row with one count can still be settled by the other: False & NA)
    same = [c for c in columns if c != "prob_full_service"]
    pd.testing.assert_frame_equal(legacy_int[same], corrected[same], check_dtype=False)
    # a column without a gap: nothing differs, nothing warns
    full = gappy_panel("float64").fillna(1.0)
    pd.testing.assert_frame_equal(quiet(fn, full), quiet(fn, full, valid_only=True))


def test_valid_only_values():
    panel = gappy_panel("float64")
    out = gb.station_outage_rates(panel, valid_only=True)
    assert out["stockout_rate"].iloc[0] == pytest.approx(2 / 3)  # bikes 0, 5, 0: two of three
    assert out["saturation_rate"].iloc[0] == pytest.approx(1 / 3)  # docks 4, 3, 0: one of three
    assert out["n_obs"].iloc[0] == 4  # n_obs still counts the rows
    legacy = gb.station_outage_rates(panel, valid_only=False)
    assert legacy["stockout_rate"].iloc[0] == 0.5 and legacy["saturation_rate"].iloc[0] == 0.25
    day = {"freq": "1D", "min_bikes": 0, "min_docks": 0}  # one bucket for the four rows
    both = gb.service_reliability_index(panel, valid_only=True, **day)
    assert both["prob_full_service"].iloc[0] == 1.0  # the two rows that have both counts qualify
    assert (
        gb.service_reliability_index(panel, valid_only=False, **day)["prob_full_service"].iloc[0]
        == 0.5
    )


def test_availability_stats_valid_only():
    panel = gappy_panel("float64")
    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        legacy = gb.availability_stats(panel)
    assert len(announces(record)) == 1
    corrected = quiet(gb.availability_stats, panel, valid_only=True)
    assert legacy["pct_time_empty"].iloc[0] == 0.5
    assert corrected["pct_time_empty"].iloc[0] == pytest.approx(2 / 3)
    assert corrected["pct_time_full"].iloc[0] == pytest.approx(1 / 3)
    assert corrected["n_obs"].iloc[0] == 4
    pd.testing.assert_frame_equal(legacy, quiet(gb.availability_stats, panel, valid_only=False))


# --- 16. a station with no count at all ------------------------------------------------------


def info_only_frame():
    return pd.DataFrame(
        {
            "num_bikes_available": [0.0, 5.0, np.nan, np.nan, 3.0],
            "num_docks_available": [4.0, 0.0, np.nan, 2.0, np.nan],
            "is_renting": [True, True, True, True, False],
            "is_returning": [True, True, True, True, False],
        }
    )


def test_station_state_default_keeps_empty_and_announces():
    frame = info_only_frame()
    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        default = gb.station_state(frame)
    assert len(announces(record)) == 1 and "unknown" in announces(record)[0]
    assert list(default) == ["empty", "full", "empty", "empty", "disabled"]
    assert list(default.cat.categories) == list(STATION_STATES)
    pd.testing.assert_series_equal(default, quiet(gb.station_state, frame, unknown=False))


def test_station_state_unknown_option():
    frame = info_only_frame()
    out = quiet(gb.station_state, frame, unknown=True)
    assert list(out) == ["empty", "full", "unknown", "empty", "disabled"]  # one count: as before
    assert list(out.cat.categories) == list(STATION_STATES_WITH_UNKNOWN)
    assert STATION_STATES == ("disabled", "virtual", "empty", "full", "normal")  # unchanged
    # nothing to announce when every row has a count; the accessor passes the option through
    counted = frame.dropna()
    assert list(quiet(gb.station_state, counted)) == ["empty", "full"]
    assert list(frame.gbfs.station_state(unknown=True))[2] == "unknown"
    # system_profile keeps its historical shares and does not warn
    quiet(gb.system_profile, frame)


# --- 13. nested zones ---------------------------------------------------------------------


def nested_zones():
    gpd = pytest.importorskip("geopandas")
    shapely = pytest.importorskip("shapely.geometry")
    big = shapely.box(2.30, 48.80, 2.40, 48.90)
    inside = shapely.box(2.33, 48.83, 2.36, 48.86)  # a restriction zone inside the service area
    return gpd.GeoDataFrame({"zone_id": ["service", "inside"]}, geometry=[big, inside], crs=4326)


def station_frame():
    rng = np.random.default_rng(0)
    return pd.DataFrame({"lat": 48.80 + rng.random(30) * 0.1, "lon": 2.30 + rng.random(30) * 0.1})


def test_coverage_zones_sum_by_default_and_union_on_request():
    zones, info = nested_zones(), station_frame()
    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        summed = gb.coverage_stats(info, zones=zones)
    assert len(announces(record)) == 1 and "dissolve_zones" in announces(record)[0]
    united = quiet(gb.coverage_stats, info, zones=zones, dissolve_zones=True)
    kept = quiet(gb.coverage_stats, info, zones=zones, dissolve_zones=False)
    assert summed["service_area_km2"] == kept["service_area_km2"]
    big_only = quiet(gb.coverage_stats, info, zones=zones.iloc[:1])
    assert united["service_area_km2"] == pytest.approx(big_only["service_area_km2"], abs=1e-3)
    assert summed["service_area_km2"] > united["service_area_km2"]
    assert united["stations_per_km2"] > summed["stations_per_km2"]
    # without an overlap there is nothing to announce and both agree
    separate = zones.iloc[:1]
    assert quiet(gb.coverage_stats, info, zones=separate, dissolve_zones=True)[
        "service_area_km2"
    ] == pytest.approx(quiet(gb.coverage_stats, info, zones=separate)["service_area_km2"])
    quiet(gb.coverage_stats, info)  # no zones: no warning


# --- 10. bins in local time ------------------------------------------------------------------


def local_panel():
    t = pd.date_range("2026-03-28T20:00", "2026-03-30T12:00", freq="1h", tz="Europe/Paris")
    return pd.DataFrame({"station_id": "a", "fetched_at": t, "num_bikes_available": range(len(t))})


def test_resample_panel_local_bins_on_request():
    panel = local_panel()
    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        default = gb.resample_panel(panel, "1D")
    assert len(announces(record)) == 1 and "keep_timezone" in announces(record)[0]
    assert str(default["fetched_at"].dt.tz) == "UTC"  # historical: UTC midnight
    assert default["fetched_at"].iloc[0] == pd.Timestamp("2026-03-28T00:00Z")
    pd.testing.assert_frame_equal(
        default, quiet(gb.resample_panel, panel, "1D", keep_timezone=False)
    )
    local = quiet(gb.resample_panel, panel, "1D", keep_timezone=True)
    assert str(local["fetched_at"].dt.tz) == "Europe/Paris"
    assert [t.hour for t in local["fetched_at"]] == [0, 0, 0]  # local midnights
    assert [t.utcoffset().total_seconds() for t in local["fetched_at"]] == [3600, 3600, 7200]
    # a short grid that divides every offset moves nothing, so it does not announce
    quiet(gb.resample_panel, panel, "15min")
    # UTC and naive inputs are unaffected by the option
    utc = panel.assign(fetched_at=panel["fetched_at"].dt.tz_convert("UTC"))
    pd.testing.assert_frame_equal(
        quiet(gb.resample_panel, utc, "1D"), quiet(gb.resample_panel, utc, "1D", keep_timezone=True)
    )


# --- 17. row order of the exogenous join -----------------------------------------------------


def shuffled_panel():
    t = pd.date_range("2026-01-01T08:00Z", periods=6, freq="1h")
    panel = pd.DataFrame(
        {"station_id": list("abcabc"), "fetched_at": t, "num_bikes_available": range(6)},
        index=[10, 11, 12, 13, 14, 15],
    )
    return panel.iloc[[3, 0, 5, 1, 4, 2]]


def weather():
    t = pd.date_range("2026-01-01T07:50Z", periods=8, freq="1h")
    return pd.DataFrame({"fetched_at": t, "temp_c": np.arange(8, dtype=float)})


def test_join_exogenous_keeps_the_input_order_on_request():
    panel = shuffled_panel()
    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        default = gb.join_exogenous_timeseries(panel, weather())
    assert len(announces(record)) == 1 and "keep_order" in announces(record)[0]
    assert default["fetched_at"].is_monotonic_increasing  # historical: sorted by time
    assert list(default.index) == list(range(6))
    kept = quiet(gb.join_exogenous_timeseries, panel, weather(), keep_order=True)
    assert list(kept.index) == list(panel.index)
    assert kept["station_id"].tolist() == panel["station_id"].tolist()
    assert kept["fetched_at"].tolist() == panel["fetched_at"].tolist()
    # the same rows: sorting the kept result by time gives the default result
    resorted = kept.sort_values("fetched_at").reset_index(drop=True)
    pd.testing.assert_frame_equal(resorted, default)
    # an input that is already sorted with a RangeIndex has nothing to announce
    ordered = panel.sort_values("fetched_at").reset_index(drop=True)
    pd.testing.assert_frame_equal(
        quiet(gb.join_exogenous_timeseries, ordered, weather()),
        quiet(gb.join_exogenous_timeseries, ordered, weather(), keep_order=True),
    )


# --- 21 and 22. the flow simulator ------------------------------------------------------------


def test_sim_rebalancing_acts_once_on_request():
    cfg = {"n_stations": 25, "days": 2, "seed": 4}
    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        _, legacy = gb.simulate_city_flows(gb.SimConfig(**cfg))
    assert any("rebalancing_once" in m for m in announces(record))
    _, explicit = quiet(gb.simulate_city_flows, gb.SimConfig(rebalancing_once=False, **cfg))
    pd.testing.assert_frame_equal(legacy, explicit)  # the default is still the 2.x behaviour
    _, once = quiet(gb.simulate_city_flows, gb.SimConfig(rebalancing_once=True, **cfg))
    assert not legacy["num_bikes_available"].equals(once["num_bikes_available"])
    # at an hourly step there is only one step in the hour: nothing differs, nothing announced
    hourly = dict(cfg, internal_minutes=60)
    _, a = quiet(gb.simulate_city_flows, gb.SimConfig(**hourly))
    _, b = quiet(gb.simulate_city_flows, gb.SimConfig(rebalancing_once=True, **hourly))
    pd.testing.assert_frame_equal(a, b)
    # no rebalancing: no announcement
    quiet(gb.simulate_city_flows, gb.SimConfig(rebalancing=False, **cfg))


def test_sim_blanked_cells_blank_the_docks_on_request():
    cfg = {
        "n_stations": 25,
        "days": 2,
        "seed": 5,
        "scraper_cell_nan": 0.1,
        "rebalancing_once": True,
    }
    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        _, status = gb.simulate_city_flows(gb.SimConfig(**cfg))
    assert any("scraper_blanks_docks" in m for m in announces(record))
    assert (
        status["num_bikes_available"].isna().any()
        and not status["num_docks_available"].isna().any()
    )
    _, blanked = quiet(gb.simulate_city_flows, gb.SimConfig(scraper_blanks_docks=True, **cfg))
    assert (
        blanked["num_bikes_available"].isna().to_numpy()
        == blanked["num_docks_available"].isna().to_numpy()
    ).all()
    # without any blanking nothing is announced
    quiet(gb.simulate_city_flows, gb.SimConfig(n_stations=10, days=1, rebalancing_once=True))


def test_calibrate_city_does_not_announce_what_it_cannot_set():
    from gbfs_toolkit.sim.compiler import calibrate_city, compute_footprint

    info, status = gb.simulate_city_flows(
        gb.SimConfig(n_stations=12, days=2, seed=1, rebalancing_once=False)
    )
    target = compute_footprint(status)
    result = quiet(calibrate_city, info, target, days=1)
    assert result["best_config"].rebalancing_once is False

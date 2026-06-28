"""Tests for the v1.7.0 consistency work: deprecations and the uniform validation contract."""

from __future__ import annotations

import warnings

import pandas as pd
import pytest

import gbfs_toolkit as gb


def _panel() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "system_id": "s",
            "station_id": ["a", "b", "a", "b"],
            "fetched_at": pd.to_datetime(
                ["2026-01-01T08:00Z", "2026-01-01T08:00Z", "2026-01-01T18:00Z", "2026-01-01T18:00Z"]
            ),
            "num_bikes_available": [5, 5, 10, 0],
        }
    )


# --- deprecations -----------------------------------------------------------


def test_dynamic_gini_index_target_col_deprecated_but_works():
    panel = _panel()
    with pytest.warns(FutureWarning, match="target_col"):
        out = gb.dynamic_gini_index(panel, target_col="num_bikes_available")
    # value_col is the new name and produces the same result
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # no warning on the new keyword
        ref = gb.dynamic_gini_index(panel, value_col="num_bikes_available")
    pd.testing.assert_frame_equal(out, ref)


def test_temporal_autocorrelation_column_deprecated_but_works():
    idx = pd.date_range("2026-01-01", periods=6, freq="1h", tz="UTC")
    panel = pd.DataFrame(
        {
            "system_id": "s",
            "station_id": "a",
            "fetched_at": idx,
            "num_bikes_available": [0, 5, 0, 5, 0, 5],
        }
    )
    with pytest.warns(FutureWarning, match="column"):
        out = gb.temporal_autocorrelation(panel, lags=(2,), column="num_bikes_available")
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        ref = gb.temporal_autocorrelation(panel, lags=(2,), value_col="num_bikes_available")
    pd.testing.assert_frame_equal(out, ref)


# --- uniform validation contract -------------------------------------------


@pytest.mark.parametrize(
    "call",
    [
        lambda: gb.concentration_metrics(pd.DataFrame({"x": [1.0]})),
        lambda: gb.lorenz_curve(pd.DataFrame({"x": [1.0]})),
        lambda: gb.morans_i(pd.DataFrame({"x": [1.0]}), "x"),
        lambda: gb.ripley_k(pd.DataFrame({"x": [1.0]}), radii=[100]),
        lambda: gb.coverage_stats(pd.DataFrame({"x": [1.0]})),
        lambda: gb.station_state(pd.DataFrame({"x": [1.0]})),
    ],
)
def test_reducers_raise_schema_error_on_missing_columns(call):
    with pytest.raises(gb.SchemaError):
        call()


def test_system_profile_stays_lenient():
    # a profile/describe must still work on a frame lacking the count columns.
    empty = pd.DataFrame({"capacity": [], "lat": [], "lon": []})
    assert gb.system_profile(empty)["n_stations"] == 0


def test_require_columns_is_public():
    assert "require_columns" in gb.__all__
    with pytest.raises(gb.SchemaError):
        gb.require_columns(pd.DataFrame({"a": [1]}), ["b"], what="test")

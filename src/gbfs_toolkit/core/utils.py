"""Shared internal helpers.

Private module (underscore-prefixed): not part of the public API and not re-exported.
It exists so the same small primitives (earth radius, the equirectangular projection, the
panel-flatten idiom, the Gini coefficient, fixed-frequency time-of-day bucketing) live in
exactly one place instead of being re-derived in every analysis module.
"""

from __future__ import annotations

import warnings
from typing import Any, TypeVar

import numpy as np
import pandas as pd

_T = TypeVar("_T")


def parse_gbfs_timestamp(value: Any) -> pd.Timestamp:
    """Parse a GBFS timestamp to a tz-aware UTC ``Timestamp`` (``NaT`` if unparseable).

    GBFS 2.x carries unix seconds; GBFS 3.x carries an RFC3339 string. The single
    parser both the I/O and normalisation layers use, so the two never drift.
    """
    if value is None:
        return pd.NaT
    if isinstance(value, (int, float)):
        return pd.to_datetime(value, unit="s", utc=True)
    try:  # numeric strings still mean unix seconds
        return pd.to_datetime(float(value), unit="s", utc=True)
    except (TypeError, ValueError):
        return pd.to_datetime(value, errors="coerce", utc=True)


def deprecated_kwarg(value: _T, *, old: str, new: str) -> _T:
    """Emit a ``FutureWarning`` for a renamed keyword and return its value unchanged.

    Helper for a one-cycle deprecation: a function keeps the old keyword as an
    opt-in alias (default ``None``) and forwards it through this so every renamed
    parameter warns identically and points at the caller.
    """
    warnings.warn(
        f"`{old}` is deprecated and will be removed in a future release; use `{new}`.",
        FutureWarning,
        stacklevel=3,
    )
    return value


#: Mean Earth radius in metres (spherical approximation), used by every distance/projection helper.
EARTH_RADIUS_M = 6_371_000.0


def panel_frame(panel: pd.DataFrame) -> pd.DataFrame:
    """Flatten a MultiIndexed panel to columns, or copy a flat frame.

    The canonical longitudinal panel is MultiIndexed by ``(system_id, station_id, fetched_at)``;
    most analysis functions want those as columns. A flat frame is copied so callers never mutate
    the input.
    """
    return panel.reset_index() if isinstance(panel.index, pd.MultiIndex) else panel.copy()


def project_meters(lat, lon) -> np.ndarray:
    """Equirectangular projection to local metres around the dataset mean latitude.

    Accurate enough for the sub-100 km neighbourhood queries the audit and the spatial metrics use.
    Returns an ``(n, 2)`` array of ``(x, y)`` metres; an empty input yields an empty ``(0, 2)`` array.
    """
    lat_r = np.deg2rad(np.asarray(lat, dtype="float64"))
    lon_r = np.deg2rad(np.asarray(lon, dtype="float64"))
    if lat_r.size == 0:
        return np.empty((0, 2), dtype="float64")
    mean_lat = float(np.nanmean(lat_r))
    x = EARTH_RADIUS_M * lon_r * np.cos(mean_lat)
    y = EARTH_RADIUS_M * lat_r
    return np.column_stack([x, y])


def num(df: pd.DataFrame, col: str) -> pd.Series:
    """Numeric view of a column (NaN where absent/unparseable)."""
    if col not in df.columns:
        return pd.Series(np.nan, index=df.index, dtype="float64")
    return pd.to_numeric(df[col], errors="coerce")


def gini(values) -> float:
    """Gini coefficient of non-negative values (0 = perfectly even, 1 = maximally concentrated)."""
    v = np.sort(np.asarray(values, dtype="float64"))
    v = v[np.isfinite(v)]
    n = v.size
    if n == 0 or v.sum() == 0:
        return float("nan")
    cum = np.cumsum(v)
    g = (n + 1 - 2 * np.sum(cum) / cum[-1]) / n
    return float(max(0.0, g))  # guard a -0/-eps from float roundoff on all-equal inputs


def offset_minutes(freq: str) -> float:
    """Minutes per fixed pandas offset alias (e.g. ``"1h"`` -> 60.0, ``"30min"`` -> 30.0).

    Raises a clear ``ValueError`` for non-fixed offsets (``"ME"``, ``"MS"``, ``"W"``,
    ``"Q"``, ``"Y"`` ...), which have no constant length and cannot index a time-of-day.
    """
    # offset.nanos is the cross-version primitive: it returns nanoseconds for a fixed
    # offset (including Day) on both pandas 2.x and 3.x, and raises ValueError for a
    # non-fixed one. pd.Timedelta(offset) cannot be used: it raises for Day on pandas 3.0.
    offset = pd.tseries.frequencies.to_offset(freq)
    try:
        return offset.nanos / 6e10
    except ValueError as exc:
        raise ValueError(
            f"{freq!r} is not a fixed-width frequency; use a constant alias such as "
            "'1h', '30min', '15min' or '1D'."
        ) from exc


def time_of_day_minutes(timestamps, freq: str) -> np.ndarray:
    """Minutes since local midnight, floored to ``freq`` buckets (a time-of-day index)."""
    ts = pd.to_datetime(timestamps)
    minutes = ts.dt.hour * 60 + ts.dt.minute + ts.dt.second / 60
    step = offset_minutes(freq)
    return (np.floor(minutes / step) * step).to_numpy()

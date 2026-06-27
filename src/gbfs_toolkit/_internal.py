"""Shared internal helpers.

Private module (underscore-prefixed): not part of the public API and not re-exported.
It exists so the same small primitives (earth radius, the equirectangular projection, the
panel-flatten idiom, the Gini coefficient, fixed-frequency time-of-day bucketing) live in
exactly one place instead of being re-derived in every analysis module.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

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


def gini(values) -> float:
    """Gini coefficient of non-negative values (0 = perfectly even, 1 = maximally concentrated)."""
    v = np.sort(np.asarray(values, dtype="float64"))
    v = v[np.isfinite(v)]
    n = v.size
    if n == 0 or v.sum() == 0:
        return float("nan")
    cum = np.cumsum(v)
    return float((n + 1 - 2 * np.sum(cum) / cum[-1]) / n)


def offset_minutes(freq: str) -> float:
    """Minutes per fixed pandas offset alias (e.g. ``"1h"`` -> 60.0, ``"30min"`` -> 30.0)."""
    return pd.tseries.frequencies.to_offset(freq).nanos / 6e10


def time_of_day_minutes(timestamps, freq: str) -> np.ndarray:
    """Minutes since local midnight, floored to ``freq`` buckets (a time-of-day index)."""
    ts = pd.to_datetime(timestamps)
    minutes = ts.dt.hour * 60 + ts.dt.minute + ts.dt.second / 60
    step = offset_minutes(freq)
    return (np.floor(minutes / step) * step).to_numpy()

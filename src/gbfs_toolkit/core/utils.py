"""Shared internal helpers.

Internal module: not part of the public API and not re-exported (its names may change in
any release).
It exists so the same small primitives (earth radius, the equirectangular projection, the
panel-flatten idiom, the Gini coefficient, fixed-frequency time-of-day bucketing) live in
exactly one place instead of being re-derived in every analysis module.
"""

from __future__ import annotations

import functools
import warnings
from collections.abc import Callable
from typing import Any, TypeVar, cast

import numpy as np
import pandas as pd

# Internal helpers: nothing here is public API (see docs/api-policy.md).
__all__: list[str] = []

_T = TypeVar("_T")
_F = TypeVar("_F", bound=Callable[..., Any])


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


def to_datetime_keep_tz(values: Any) -> pd.Series:
    """Parse timestamps keeping their time zone: aware stays as is, naive is read as UTC.

    ``pd.to_datetime(..., utc=True)`` converts a *local-time* panel back to UTC, which
    silently shifts every hour-of-day and weekday computed afterwards. Mixed offsets, which
    have no single zone, are converted to UTC.
    """
    try:
        ts = pd.Series(pd.to_datetime(values))
    except (ValueError, TypeError):
        return pd.Series(pd.to_datetime(values, utc=True))
    return ts.dt.tz_localize("UTC") if ts.dt.tz is None else ts


def floor_time(ts: pd.Series, freq: str) -> pd.Series:
    """``ts.dt.floor(freq)`` that also works on local time across a daylight-saving change.

    pandas refuses to floor a local timestamp that is ambiguous (the repeated hour when
    the clocks go back) or lands on a missing hour. The wall clock is floored as usual and
    the repeated hour is resolved from each timestamp's own UTC offset (the first pass has
    the larger offset), so the result is the same as the plain floor wherever that works.
    """
    ts = pd.Series(ts)
    try:
        return ts.dt.floor(freq)
    except Exception:  # noqa: BLE001  (pytz's AmbiguousTimeError is not a ValueError)
        if ts.dt.tz is None:
            raise
    offset = ts.dt.tz_localize(None) - ts.dt.tz_convert("UTC").dt.tz_localize(None)
    first_pass = (offset == offset.max()).to_numpy()
    return ts.dt.floor(freq, ambiguous=first_pass, nonexistent="shift_forward")


def unix_seconds(index: Any) -> np.ndarray:
    """Unix seconds (int64) of a datetime index or series, whatever its resolution.

    ``DatetimeIndex.view("int64")`` is in the index's own unit (nanoseconds before
    pandas 3, microseconds for a ``date_range`` of dates under pandas 3), so dividing it
    by a fixed power of ten is only right on one of them. A naive index is read as UTC.
    """
    idx = pd.DatetimeIndex(index)
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    return np.asarray((idx - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(seconds=1), dtype="int64")


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


def warn_deprecated(
    what: str,
    *,
    since: str,
    removal: str | None = None,
    alternative: str | None = None,
    stacklevel: int = 2,
) -> None:
    """Emit the library's standard deprecation warning (a ``FutureWarning``).

    The deprecation policy (docs/api-policy.md) is: a public name or behaviour is
    deprecated in a minor release, keeps working with this warning for at least one
    further minor release, and is removed only in the next major release. The message
    always names the version that deprecated it, the planned removal and the
    replacement, so users can act on it. ``FutureWarning`` (not ``DeprecationWarning``)
    is used, as in pandas, because it is shown to end users by default.

    Parameters
    ----------
    what : str
        What is deprecated, e.g. ``"gbfs_toolkit.old_name"`` or ``"`strict=True`"``.
    since : str
        The release that deprecated it, e.g. ``"2.1.0"``.
    removal : str, optional
        The release that will remove it (default: "the next major release").
    alternative : str, optional
        What to use instead.
    stacklevel : int, default 2
        Passed to `warnings.warn`; 2 points at the caller of the function that warns.

    Examples
    --------
    >>> import warnings
    >>> with warnings.catch_warnings(record=True) as caught:
    ...     warnings.simplefilter("always")
    ...     warn_deprecated("old_name", since="2.1.0", alternative="new_name")
    >>> str(caught[0].message)
    'old_name is deprecated since gbfs-toolkit 2.1.0 and will be removed in the next major release; use new_name instead.'
    """
    message = f"{what} is deprecated since gbfs-toolkit {since} and will be removed in "
    message += f"gbfs-toolkit {removal}" if removal else "the next major release"
    message += f"; use {alternative} instead." if alternative else "."
    warnings.warn(message, FutureWarning, stacklevel=stacklevel + 1)


def warn_default_change(
    what: str, *, option: str, new: str, since: str = "2.1.0", stacklevel: int = 2
) -> None:
    """Announce that a default will change in 3.0, when this call's result is affected by it.

    For an opt-in correction (see "Open points" in the changelog): the option keeps its
    current default in the 2.x series; it is left unset by the caller and the input is one on
    which the two behaviours differ, so the warning names what changes and how to choose now.
    It is a ``FutureWarning`` like the deprecations of the API policy and, like them, names the
    release that announced it, the release that changes it and the way to adopt it.
    ``stacklevel`` counts from the function that calls this helper (2 = its caller).
    """
    warnings.warn(
        f"{option}: the default changes in gbfs-toolkit 3.0 (announced in {since}); today "
        f"{what}. Pass {new} to adopt the new behaviour now, or the other value to keep the "
        "current one and silence this warning.",
        FutureWarning,
        stacklevel=stacklevel + 1,
    )


def has_float_gaps(*columns: pd.Series) -> bool:
    """Whether a count column is a NumPy float holding at least one missing value.

    That is the case in which rates are computed differently for a float column (a missing count
    is counted as "not empty") and for a nullable integer one (the row is skipped).
    """
    return any(
        isinstance(c.dtype, np.dtype) and c.dtype.kind == "f" and bool(c.isna().any())
        for c in columns
    )


def valid_flag(condition: pd.Series, count: pd.Series) -> np.ndarray:
    """``condition`` as 0.0/1.0 with NaN where ``count`` is missing, whatever the count's dtype.

    The mean of this array is the rate over the rows that have a count.
    """
    ok = condition.fillna(False).to_numpy(dtype=bool)
    return np.where(count.isna().to_numpy(), np.nan, ok.astype("float64"))


def deprecated(
    *, since: str, removal: str | None = None, alternative: str | None = None
) -> Callable[[_F], _F]:
    """Decorator marking a public function as deprecated (see `warn_deprecated`).

    The wrapped function behaves exactly as before and warns at each call, pointing
    at the caller's line; its docstring gains a ``Deprecated`` note so the API
    reference shows it.

    Examples
    --------
    >>> import warnings
    >>> @deprecated(since="2.1.0", alternative="gbfs_toolkit.new_name")
    ... def old_name(x):
    ...     \"\"\"Double x.\"\"\"
    ...     return 2 * x
    >>> with warnings.catch_warnings(record=True) as caught:
    ...     warnings.simplefilter("always")
    ...     old_name(2)
    4
    >>> caught[0].category.__name__
    'FutureWarning'
    """

    def decorate(func: _F) -> _F:
        name = f"{func.__module__}.{func.__qualname__}"

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            warn_deprecated(name, since=since, removal=removal, alternative=alternative)
            return func(*args, **kwargs)

        note = f"Deprecated since {since}"
        note += f"; use {alternative} instead." if alternative else "."
        wrapper.__doc__ = f'{func.__doc__ or ""}\n\n    !!! warning "Deprecated"\n        {note}\n'
        return cast(_F, wrapper)

    return decorate


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

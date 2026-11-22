"""Small helpers shared by the data-lake modules (internal, not public API)."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd

from gbfs_toolkit.core.errors import GBFSValidationError

__all__: list[str] = []


def require_pyarrow(what: str) -> Any:
    """Import and return ``pyarrow``, or raise an ``ImportError`` that names the extra."""
    try:
        import pyarrow

        return pyarrow
    except ImportError as e:  # pragma: no cover (exercised only without the extra)
        raise ImportError(
            f"{what} needs pyarrow. Install it with `pip install gbfs-toolkit[parquet]`."
        ) from e


def to_utc(values: Any, *, what: str = "timestamps") -> pd.Series:
    """A tz-aware UTC ``datetime64`` series: naive values are read as UTC, aware ones converted.

    Raises ``ValueError`` for values that cannot be parsed, so a typo never silently
    becomes ``NaT`` in a quality report.
    """
    s = pd.Series(values)
    if not isinstance(s.dtype, pd.DatetimeTZDtype):
        parsed = pd.to_datetime(s, errors="coerce", utc=True, format="mixed")
        bad = parsed.isna() & s.notna()
        if bad.any():
            raise ValueError(f"{what}: {int(bad.sum())} value(s) cannot be parsed as timestamps")
        return parsed
    return s.dt.tz_convert("UTC")


def fixed_timedelta(freq: str | pd.Timedelta, *, what: str = "frequency") -> pd.Timedelta:
    """A fixed-width ``Timedelta`` from an offset alias such as ``"15min"``, ``"1h"`` or ``"1D"``."""
    if isinstance(freq, pd.Timedelta):
        td = freq
    else:
        try:
            td = pd.Timedelta(pd.tseries.frequencies.to_offset(freq).nanos, unit="ns")
        except ValueError as exc:
            raise ValueError(
                f"{what}: {freq!r} is not a fixed-width frequency; use '1min', '15min', '1h' or '1D'."
            ) from exc
    if td <= pd.Timedelta(0):
        raise ValueError(f"{what}: must be positive, got {freq!r}")
    return td


def need_columns(df: pd.DataFrame, columns: list[str], *, what: str) -> None:
    """Raise the library's ``SchemaError`` when ``columns`` are missing."""
    from gbfs_toolkit.core.models import require_columns

    require_columns(df, columns, what=what)


def atomic_write(path: Path, writer: Callable[[Path], Any]) -> None:
    """Write through a temporary file in the same folder, then rename it over ``path``.

    A reader never sees a half-written file, and an interrupted write leaves the previous
    file intact. ``writer`` receives the temporary path.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        writer(tmp)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def check(condition: bool, message: str) -> None:
    """Raise ``GBFSValidationError`` with ``message`` unless ``condition`` holds."""
    if not condition:
        raise GBFSValidationError(message)

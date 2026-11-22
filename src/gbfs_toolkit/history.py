"""Keep a dated version of a metadata feed only when its content changes.

!!! warning "Experimental"
    Part of the experimental data-lake modules added in 2.1.0: names, parameters and output
    columns may change in a minor release (see the API policy).

``system_information``, ``vehicle_types``, ``system_pricing_plans``, ``system_regions`` and
``station_information`` change a few times a year, but a collector fetches them every day.
Overwriting them loses the past; keeping each fetch repeats the same bytes hundreds of times.
`record_version` keeps one file per *distinct content*, named after the UTC day of the
fetch::

    <history_dir>/2026-01-14.parquet     the content as of 14 January
    <history_dir>/2026-06-02.parquet     it changed on 2 June

Two fetches have the same content when their rows are equal **ignoring**

* the fetch time (``fetched_at`` changes at every call, see ``ignore``),
* the order of the rows,
* the order of the columns,
* the order of the keys inside a JSON text or a dict (``'{"a":1,"b":2}'`` equals
  ``'{"b":2,"a":1}'``),
* ``1`` against ``1.0``, and a column that is absent against a column that is empty.

`content_fingerprint` is that comparison, as a SHA-256 you can store. The list order
inside a JSON array *does* matter. A version of a closed day is never rewritten; the version
of the current UTC day may be, so a second fetch the same day replaces the first.

Parquet needs ``pip install gbfs-toolkit[parquet]``; the fingerprint alone needs nothing.

Examples
--------
>>> import pandas as pd
>>> from gbfs_toolkit.history import content_fingerprint
>>> a = pd.DataFrame({"id": ["x", "y"], "rules": ['{"p": 1, "q": 2}', "[]"],
...                   "fetched_at": pd.to_datetime(["2026-01-01T00:00Z"] * 2)})
>>> b = a.iloc[::-1].assign(rules=['[]', '{"q": 2, "p": 1}'],
...                         fetched_at=pd.to_datetime(["2026-02-01T00:00Z"] * 2))
>>> content_fingerprint(a) == content_fingerprint(b)
True
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from gbfs_toolkit.core._common import atomic_write, need_columns, require_pyarrow, to_utc

__all__ = [
    "VOLATILE_COLUMNS",
    "VersionResult",
    "content_fingerprint",
    "list_versions",
    "read_version",
    "record_version",
]

_log = logging.getLogger(__name__)

#: Columns that change at every fetch and say nothing about the content.
VOLATILE_COLUMNS: tuple[str, ...] = ("fetched_at",)


def _is_na(value: Any) -> bool:
    if value is None or value is pd.NA or value is pd.NaT:
        return True
    return isinstance(value, float) and value != value


def _canonical(value: Any) -> Any:
    """A value in a form that does not depend on key order, ``1`` vs ``1.0`` or the JSON spelling."""
    if isinstance(value, str) and value[:1] in "[{":
        try:
            return _canonical(json.loads(value))
        except ValueError:
            return value
    if hasattr(value, "item") and not isinstance(value, (list, dict, str)):
        try:
            value = value.item()
        except (ValueError, AttributeError):  # a multi-element array
            value = value.tolist()
    if isinstance(value, bool):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {str(k): _canonical(v) for k, v in value.items() if not _is_na(v)}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    if isinstance(value, pd.Timestamp):
        return value.tz_convert("UTC").isoformat() if value.tzinfo else value.isoformat()
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    return value


def content_fingerprint(
    df: pd.DataFrame, *, ignore: tuple[str, ...] | list[str] = VOLATILE_COLUMNS
) -> str:
    """SHA-256 (hex) of a frame's content, as defined in the module description.

    Parameters
    ----------
    df : pandas.DataFrame
        A metadata table (or any small table).
    ignore : sequence of str, default ``("fetched_at",)``
        Columns left out of the comparison.

    Examples
    --------
    >>> import pandas as pd
    >>> one = pd.DataFrame({"a": [1, 2]})
    >>> content_fingerprint(one) == content_fingerprint(pd.DataFrame({"a": [2.0, 1.0]}))
    True
    >>> content_fingerprint(one) == content_fingerprint(pd.DataFrame({"a": [1, 3]}))
    False
    """
    skip = set(ignore)
    lines = []
    for record in df.to_dict(orient="records"):
        row = {}
        for key, value in record.items():
            if key in skip or (not isinstance(value, (list, dict)) and _is_na(value)):
                continue
            canon = _canonical(value)
            if canon is not None:
                row[str(key)] = canon
        lines.append(json.dumps(row, sort_keys=True, ensure_ascii=False, default=str))
    lines.sort()
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def list_versions(history_dir: str | Path) -> pd.DataFrame:
    """The dated versions present: ``version_date`` (a ``date``) and ``path``, oldest first.

    Files whose name is not ``YYYY-MM-DD.parquet`` are ignored.
    """
    rows = []
    folder = Path(history_dir)
    if folder.is_dir():
        for f in sorted(folder.glob("*.parquet")):
            try:
                rows.append({"version_date": dt.date.fromisoformat(f.stem), "path": f})
            except ValueError:
                continue
    return pd.DataFrame(rows, columns=["version_date", "path"])


def read_version(
    history_dir: str | Path, version: str | dt.date = "latest", *, asof: bool = False
) -> pd.DataFrame:
    """Read a version: ``"latest"``, or the one of a given day.

    With ``asof=True`` a date selects the version that was in force on that day (the latest one
    dated on or before it), which is what an analysis of a past period wants.

    Raises
    ------
    FileNotFoundError
        If no version matches.
    """
    require_pyarrow("read_version")
    versions = list_versions(history_dir)
    if versions.empty:
        raise FileNotFoundError(f"no dated version in {history_dir}")
    if isinstance(version, str) and version == "latest":
        row = versions.iloc[-1]
    else:
        day = version if isinstance(version, dt.date) else dt.date.fromisoformat(str(version))
        if asof:
            before = versions[versions["version_date"] <= day]
            if before.empty:
                raise FileNotFoundError(f"no version of {history_dir} on or before {day}")
            row = before.iloc[-1]
        else:
            hit = versions[versions["version_date"] == day]
            if hit.empty:
                raise FileNotFoundError(f"no version of {history_dir} dated {day}")
            row = hit.iloc[0]
    return pd.read_parquet(row["path"])


@dataclass(frozen=True)
class VersionResult:
    """What `record_version` decided.

    ``action`` is ``"written"`` (a new or refreshed version), ``"unchanged"`` (same content as
    the latest version), ``"kept_closed_day"`` (a different version of a closed day already
    exists and is never rewritten) or ``"older_than_latest"`` (the fetch predates the latest
    version; nothing is done).
    """

    action: str
    version_date: dt.date
    path: Path
    fingerprint: str


def record_version(
    df: pd.DataFrame,
    history_dir: str | Path,
    *,
    time_col: str = "fetched_at",
    ignore: tuple[str, ...] | list[str] = VOLATILE_COLUMNS,
    dry_run: bool = False,
    today: dt.date | None = None,
) -> VersionResult:
    """Save ``df`` as a dated version of ``history_dir`` unless its content did not change.

    The version is dated by the UTC day of the latest ``time_col`` in ``df``. With ``dry_run``
    nothing is written, and the result says what would have been. ``today`` overrides the clock
    (tests).

    Raises
    ------
    ValueError
        If ``df`` has no usable time to date the version.

    Examples
    --------
    >>> import tempfile, pandas as pd
    >>> a = pd.DataFrame({"name": ["Demo"], "fetched_at": pd.to_datetime(["2026-01-05T10:00Z"])})
    >>> with tempfile.TemporaryDirectory() as d:
    ...     first = record_version(a, d, today=pd.Timestamp("2026-02-01").date())
    ...     again = record_version(a.assign(fetched_at=pd.Timestamp("2026-01-06T10:00Z")), d,
    ...                            today=pd.Timestamp("2026-02-01").date())
    >>> first.action, again.action
    ('written', 'unchanged')
    """
    need_columns(df, [time_col], what="record_version")
    times = to_utc(df[time_col], what=time_col).dropna()
    if times.empty:
        raise ValueError(f"record_version: {time_col} holds no usable time to date the version")
    day = times.max().date()
    folder = Path(history_dir)
    target = folder / f"{day.isoformat()}.parquet"
    fingerprint = content_fingerprint(df, ignore=ignore)
    current = today or dt.datetime.now(dt.timezone.utc).date()
    versions = list_versions(folder)
    if not versions.empty:
        latest = versions.iloc[-1]
        if content_fingerprint(pd.read_parquet(latest["path"]), ignore=ignore) == fingerprint:
            return VersionResult("unchanged", latest["version_date"], latest["path"], fingerprint)
        if target.exists() and day < current:
            _log.info("version of the closed day %s already exists; kept", day)
            return VersionResult("kept_closed_day", day, target, fingerprint)
        if latest["version_date"] > day:
            _log.info("fetch of %s is older than the latest version; nothing done", day)
            return VersionResult("older_than_latest", day, latest["path"], fingerprint)
    if not dry_run:
        require_pyarrow("record_version")
        atomic_write(target, lambda tmp: df.to_parquet(tmp, index=False, compression="zstd"))
        _log.info("new version of %s: %s", folder, target.name)
    return VersionResult("written", day, target, fingerprint)

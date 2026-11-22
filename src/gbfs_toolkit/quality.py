"""Coverage, collection gaps, silent feeds and an incident registry for GBFS snapshots.

!!! warning "Experimental"
    Part of the experimental data-lake modules added in 2.1.0: names, parameters and output
    columns may change in a minor release (see the API policy).

A collection of snapshots is only as useful as what you know about its holes. This module
answers, for each system and each UTC day, *how many of the expected polls arrived*, and
labels the day:

``ok``
    at least ``ok_threshold_pct`` (95 % by default) of the expected polls arrived;
``partial``
    some arrived, not enough, and nothing explains it;
``outage_collector``
    the day overlaps a gap of the collection itself (no poll from *any* system for an hour or
    more) or an incident you declared;
``outage_operator``
    the collection was running, yet nothing came from this system.

It also flags values that are ambiguous at the source, with three row-level indicators
(`add_quality_indicators`) that **flag and never remove**: nothing here drops a row, and
there is no cleaning pipeline; what to do with a flagged row is the analysis's decision.

``field_unsupported_by_operator``
    an operator that publishes ``0`` for every station for the whole period does not publish
    the field; the column is blanked and the field named;
``both_zero_suspect``
    a station of positive capacity reporting no bike *and* no free dock, more often a
    placeholder than a real state;
``network_all_zero_anomaly``
    a poll in which (almost) every station of a system reports zero.

Incidents are kept in a small registry (`INCIDENT_COLUMNS`) that you can read, write and
extend, and that `detect_incidents` completes with the gaps and silent feeds it finds.

Examples
--------
>>> import pandas as pd
>>> from gbfs_toolkit.quality import daily_coverage
>>> times = pd.date_range("2026-03-01", periods=1440, freq="min", tz="UTC")
>>> snaps = pd.DataFrame({"system_id": "demo", "station_id": "s1", "fetched_at": times})
>>> cov = daily_coverage(snaps)
>>> row = cov.iloc[0]
>>> row["date_utc"].isoformat(), int(row["actual_polls"]), row["status"]
('2026-03-01', 1440, 'ok')
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from gbfs_toolkit.core._common import fixed_timedelta, need_columns, to_utc
from gbfs_toolkit.core.errors import GBFSValidationError

__all__ = [
    "STATUS_OK",
    "STATUS_PARTIAL",
    "STATUS_OUTAGE_COLLECTOR",
    "STATUS_OUTAGE_OPERATOR",
    "STATUSES",
    "CAUSES",
    "COVERAGE_COLUMNS",
    "INCIDENT_COLUMNS",
    "DEFAULT_OK_THRESHOLD_PCT",
    "DEFAULT_MIN_GAP",
    "DEFAULT_ALL_ZERO_SHARE",
    "QualityReport",
    "incident_registry",
    "add_incident",
    "read_incidents",
    "write_incidents",
    "incidents_overlapping",
    "find_collector_gaps",
    "daily_coverage",
    "find_silent_feeds",
    "detect_incidents",
    "assess",
    "field_unsupported_by_operator",
    "add_quality_indicators",
]

_log = logging.getLogger(__name__)

STATUS_OK = "ok"
STATUS_PARTIAL = "partial"
STATUS_OUTAGE_COLLECTOR = "outage_collector"
STATUS_OUTAGE_OPERATOR = "outage_operator"
#: The four labels of a system-day.
STATUSES: tuple[str, ...] = (
    STATUS_OK,
    STATUS_PARTIAL,
    STATUS_OUTAGE_COLLECTOR,
    STATUS_OUTAGE_OPERATOR,
)

#: Causes an incident can carry. ``unreadable_file`` (a truncated file left out of an analysis)
#: and ``ambiguous_missing_value`` (a period in which a value and its absence cannot be told
#: apart, for instance because an older collector wrote ``0`` for a missing field) are declared
#: by you; the two outages are also detected.
CAUSES: tuple[str, ...] = (
    "outage_collector",
    "outage_operator",
    "unreadable_file",
    "ambiguous_missing_value",
)

#: Columns of `daily_coverage`.
COVERAGE_COLUMNS: list[str] = [
    "date_utc",
    "system_id",
    "expected_polls",
    "actual_polls",
    "completeness_pct",
    "units_reporting_median",
    "both_zero_pct",
    "status",
]

#: Columns of the incident registry. ``end_utc`` empty (``NaT``) means *ongoing*; ``scope`` is
#: ``"all"`` or comma-separated system identifiers.
INCIDENT_COLUMNS: list[str] = [
    "incident_id",
    "start_utc",
    "end_utc",
    "scope",
    "cause",
    "summary",
]

#: A day is ``ok`` from this share of the expected polls.
DEFAULT_OK_THRESHOLD_PCT = 95.0
#: Time without a poll from any system that counts as a collection gap.
DEFAULT_MIN_GAP = "60min"
#: Share of rows at zero in one poll above which the poll is a ``network_all_zero_anomaly``.
DEFAULT_ALL_ZERO_SHARE = 0.95

_MINUTE = pd.Timedelta(minutes=1)
_DAY = pd.Timedelta(days=1)
_FAR_FUTURE = pd.Timestamp("2262-01-01", tz="UTC")  # an open-ended incident
_COUNT_COLS = ("num_bikes_available", "num_docks_available")
_Interval = tuple[pd.Timestamp, pd.Timestamp]


# --------------------------------------------------------------------------------------
# Incident registry
# --------------------------------------------------------------------------------------


def _empty_registry() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "incident_id": pd.Series(dtype="string"),
            "start_utc": pd.Series(dtype="datetime64[ns, UTC]"),
            "end_utc": pd.Series(dtype="datetime64[ns, UTC]"),
            "scope": pd.Series(dtype="string"),
            "cause": pd.Series(dtype="string"),
            "summary": pd.Series(dtype="string"),
        }
    )


def incident_registry(
    incidents: pd.DataFrame | Iterable[Mapping[str, Any]] | None = None,
) -> pd.DataFrame:
    """Validate incidents and return them as a registry frame (`INCIDENT_COLUMNS`).

    ``incidents`` is a frame or an iterable of dicts with the registry's keys. ``scope`` defaults
    to ``"all"`` and ``end_utc`` to *ongoing*; times are read as UTC. A problem raises
    ``GBFSValidationError`` (unknown cause, duplicated id, end before start).

    Examples
    --------
    >>> reg = incident_registry([{
    ...     "incident_id": "power-cut", "start_utc": "2026-03-02T10:00Z",
    ...     "end_utc": "2026-03-02T14:00Z", "cause": "outage_collector",
    ...     "summary": "Power cut at the collection site."}])
    >>> reg.loc[0, ["incident_id", "scope", "cause"]].tolist()
    ['power-cut', 'all', 'outage_collector']
    """
    if incidents is None:
        return _empty_registry()
    df = incidents.copy() if isinstance(incidents, pd.DataFrame) else pd.DataFrame(list(incidents))
    if df.empty:
        return _empty_registry()
    need_columns(df, ["incident_id", "start_utc", "cause"], what="incident_registry")
    for col, default in (("end_utc", pd.NaT), ("scope", "all"), ("summary", "")):
        if col not in df.columns:
            df[col] = default
    df = df[INCIDENT_COLUMNS].copy()
    df["start_utc"] = to_utc(df["start_utc"], what="start_utc")
    df["end_utc"] = pd.to_datetime(df["end_utc"].replace("", None), utc=True, format="mixed")
    df["scope"] = df["scope"].fillna("all").replace("", "all").astype("string")
    df["incident_id"] = df["incident_id"].astype("string")
    df["cause"] = df["cause"].astype("string")
    df["summary"] = df["summary"].fillna("").astype("string")
    bad = sorted(set(df["cause"]) - set(CAUSES))
    if bad:
        raise GBFSValidationError(f"unknown incident cause(s) {bad}; expected one of {CAUSES}")
    dup = df["incident_id"][df["incident_id"].duplicated()].tolist()
    if dup:
        raise GBFSValidationError(f"duplicated incident_id: {sorted(set(dup))}")
    backwards = df["end_utc"].notna() & (df["end_utc"] < df["start_utc"])
    if backwards.any():
        raise GBFSValidationError(
            f"incident(s) {df.loc[backwards, 'incident_id'].tolist()} end before they start"
        )
    return df.sort_values(["start_utc", "incident_id"]).reset_index(drop=True)


def add_incident(
    registry: pd.DataFrame | None,
    incident_id: str,
    start: str | pd.Timestamp,
    end: str | pd.Timestamp | None = None,
    *,
    cause: str,
    scope: str = "all",
    summary: str = "",
) -> pd.DataFrame:
    """A new registry that holds ``registry`` plus one incident (the input is not modified).

    Examples
    --------
    >>> reg = add_incident(None, "site-move", "2026-03-02", "2026-03-03",
    ...                    cause="outage_collector", summary="Moved the collector.")
    >>> len(add_incident(reg, "feed-down", "2026-03-05", cause="outage_operator", scope="demo"))
    2
    """
    row = pd.DataFrame(
        [
            {
                "incident_id": incident_id,
                "start_utc": start,
                "end_utc": end if end is not None else pd.NaT,
                "scope": scope,
                "cause": cause,
                "summary": summary,
            }
        ]
    )
    return incident_registry(pd.concat([incident_registry(registry), row], ignore_index=True))


def _iso(ts: Any) -> str | None:
    return None if pd.isna(ts) else pd.Timestamp(ts).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_incidents(registry: pd.DataFrame, path: str | Path) -> Path:
    """Write the registry as ``.json`` (a list of objects) or ``.csv``, by the file suffix.

    Timestamps are ISO 8601 in UTC (``2026-03-02T10:00:00Z``); an ongoing incident has a null
    ``end_utc`` in JSON and an empty cell in CSV.
    """
    out = Path(path)
    reg = incident_registry(registry)
    records = [
        {
            "incident_id": str(r.incident_id),
            "start_utc": _iso(r.start_utc),
            "end_utc": _iso(r.end_utc),
            "scope": str(r.scope),
            "cause": str(r.cause),
            "summary": str(r.summary),
        }
        for r in reg.itertuples(index=False)
    ]
    suffix = out.suffix.lower()
    if suffix not in (".json", ".csv"):
        raise ValueError(f"write_incidents: use a .json or .csv path, got {out.name!r}")
    out.parent.mkdir(parents=True, exist_ok=True)
    if suffix == ".json":
        out.write_text(json.dumps(records, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    else:
        pd.DataFrame(records, columns=INCIDENT_COLUMNS).to_csv(out, index=False)
    return out


def read_incidents(path: str | Path) -> pd.DataFrame:
    """Read a registry written by `write_incidents` (``.json`` or ``.csv``)."""
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix == ".json":
        return incident_registry(json.loads(p.read_text(encoding="utf-8")))
    if suffix == ".csv":
        return incident_registry(pd.read_csv(p, keep_default_na=False))
    raise ValueError(f"read_incidents: use a .json or .csv path, got {p.name!r}")


def _scope_systems(scope: str) -> set[str] | None:
    """``None`` for ``"all"``, else the set of system identifiers."""
    if scope.strip() == "all":
        return None
    return {s.strip() for s in scope.split(",") if s.strip()}


def incidents_overlapping(
    registry: pd.DataFrame,
    start: str | pd.Timestamp,
    end: str | pd.Timestamp,
    systems: Iterable[str] | None = None,
) -> pd.DataFrame:
    """The incidents that overlap ``[start, end)`` and touch ``systems`` (all, when ``None``).

    An incident with scope ``"all"`` touches every system; an ongoing one never ends.

    Examples
    --------
    >>> reg = incident_registry([
    ...     {"incident_id": "a", "start_utc": "2026-03-01", "end_utc": "2026-03-02",
    ...      "cause": "outage_collector"},
    ...     {"incident_id": "b", "start_utc": "2026-04-01", "cause": "outage_operator",
    ...      "scope": "demo"}])
    >>> incidents_overlapping(reg, "2026-03-01", "2026-03-10")["incident_id"].tolist()
    ['a']
    """
    reg = incident_registry(registry)
    if reg.empty:
        return reg
    lo, hi = to_utc([start]).iloc[0], to_utc([end]).iloc[0]
    wanted = None if systems is None else set(systems)
    keep = []
    for r in reg.itertuples(index=False):
        ends = _FAR_FUTURE if pd.isna(r.end_utc) else r.end_utc
        scope = _scope_systems(str(r.scope))
        touches = scope is None or wanted is None or bool(scope & wanted)
        keep.append(bool(r.start_utc < hi and ends > lo and touches))
    return reg[np.asarray(keep, dtype=bool)].reset_index(drop=True)


# --------------------------------------------------------------------------------------
# Intervals
# --------------------------------------------------------------------------------------


def _intervals(registry: pd.DataFrame, cause: str, system: str | None = None) -> list[_Interval]:
    """Intervals of the registry's incidents of ``cause`` (those touching ``system``, if given)."""
    out: list[_Interval] = []
    for r in registry.itertuples(index=False):
        if r.cause != cause:
            continue
        scope = _scope_systems(str(r.scope))
        if system is not None and scope is not None and system not in scope:
            continue
        out.append((r.start_utc, _FAR_FUTURE if pd.isna(r.end_utc) else r.end_utc))
    return out


def _subtract(start: pd.Timestamp, end: pd.Timestamp, removed: list[_Interval]) -> list[_Interval]:
    """``[start, end)`` minus the removed intervals: the pieces that remain."""
    pieces: list[_Interval] = [(start, end)]
    for x, y in removed:
        nxt: list[_Interval] = []
        for u, v in pieces:
            if y <= u or x >= v:
                nxt.append((u, v))
                continue
            if u < x:
                nxt.append((u, x))
            if y < v:
                nxt.append((y, v))
        pieces = nxt
    return pieces


def _overlaps(intervals: list[_Interval], start: pd.Timestamp, end: pd.Timestamp) -> bool:
    return any(a < end and b > start for a, b in intervals)


# --------------------------------------------------------------------------------------
# Gaps and coverage
# --------------------------------------------------------------------------------------


def find_collector_gaps(
    snapshots: pd.DataFrame,
    *,
    min_gap: str | pd.Timedelta = DEFAULT_MIN_GAP,
    known: pd.DataFrame | None = None,
    time_col: str = "fetched_at",
) -> pd.DataFrame:
    """Stretches in which **no system at all** was polled for ``min_gap`` or more.

    When every system goes quiet together, the cause is the collection, not the operators.
    Polls are compared at one-minute resolution. ``known`` is a registry: the time it already
    explains with ``outage_collector`` incidents is subtracted, and only the stretches that
    remain and last at least ``min_gap`` are reported.

    Returns
    -------
    pandas.DataFrame
        ``start_utc, end_utc, duration`` (a ``Timedelta``), one row per gap.

    Examples
    --------
    >>> import pandas as pd
    >>> t = pd.to_datetime(["2026-03-01T00:00Z", "2026-03-01T00:01Z", "2026-03-01T05:00Z"])
    >>> gaps = find_collector_gaps(pd.DataFrame({"fetched_at": t}))
    >>> str(gaps.loc[0, "duration"])
    '0 days 04:58:00'
    """
    need_columns(snapshots, [time_col], what="find_collector_gaps")
    gap = fixed_timedelta(min_gap, what="min_gap")
    minutes = to_utc(snapshots[time_col], what=time_col).dt.floor("min").drop_duplicates()
    minutes = minutes.sort_values().reset_index(drop=True)
    declared = _intervals(incident_registry(known), "outage_collector")
    rows = []
    for prev, nxt in zip(minutes[:-1], minutes[1:], strict=True):
        if nxt - prev <= gap:
            continue
        for u, v in _subtract(prev + _MINUTE, nxt, declared):
            if v - u >= gap:
                rows.append({"start_utc": u, "end_utc": v, "duration": v - u})
    out = pd.DataFrame(rows, columns=["start_utc", "end_utc", "duration"])
    if not rows:
        out["start_utc"] = out["start_utc"].astype("datetime64[ns, UTC]")
        out["end_utc"] = out["end_utc"].astype("datetime64[ns, UTC]")
        out["duration"] = out["duration"].astype("timedelta64[ns]")
    return out


def _both_zero(df: pd.DataFrame) -> pd.Series | None:
    """Per row: both counts are zero (``False`` where one is missing); ``None`` if no counts."""
    if not all(c in df.columns for c in _COUNT_COLS):
        return None
    b = pd.to_numeric(df[_COUNT_COLS[0]], errors="coerce")
    d = pd.to_numeric(df[_COUNT_COLS[1]], errors="coerce")
    return ((b == 0) & (d == 0)).fillna(False).astype(bool)


def _as_day(value: str | pd.Timestamp | None) -> dt.date | None:
    return None if value is None else to_utc([value]).iloc[0].date()


def _empty_coverage() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype="object") for c in COVERAGE_COLUMNS})


def daily_coverage(
    snapshots: pd.DataFrame,
    *,
    expected_polls: int | None = None,
    ok_threshold_pct: float = DEFAULT_OK_THRESHOLD_PCT,
    poll_resolution: str | pd.Timedelta = "1min",
    known_incidents: pd.DataFrame | None = None,
    min_collector_gap: str | pd.Timedelta = DEFAULT_MIN_GAP,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
    time_col: str = "fetched_at",
) -> pd.DataFrame:
    """Per system and UTC day: polls expected and obtained, completeness and a status.

    A *poll* is a distinct ``poll_resolution`` slot (a minute by default) in which the system has
    at least one row. ``expected_polls`` defaults to the number of slots in a day (1440 for a
    poll every minute; pass ``poll_resolution="15min"`` for 96).

    The window of each system starts on its first day; ``start`` and ``end`` (UTC days,
    inclusive) bound it. By default ``end`` is the last day present in the data, so **a day
    still being collected counts as partial**: pass yesterday's date to leave it out. Days with
    no row at all between a system's first day and ``end`` are reported with zero polls.

    ``known_incidents`` (a registry) and the gaps found in ``snapshots`` explain missing polls
    as ``outage_collector``; a declared ``outage_operator`` incident of a system explains its own.

    Parameters
    ----------
    snapshots : pandas.DataFrame
        One row per station (or vehicle) per poll, with ``system_id`` and ``time_col``
        (tz-aware UTC; naive is read as UTC). ``num_bikes_available`` and
        ``num_docks_available`` add ``both_zero_pct``.
    ok_threshold_pct : float, default 95.0
        Completeness from which a day is ``ok``.

    Returns
    -------
    pandas.DataFrame
        `COVERAGE_COLUMNS`. ``units_reporting_median`` is the median number of rows per
        poll (stations or vehicles published); ``both_zero_pct`` the share of the day's rows at
        zero bikes and zero docks, in the raw values you passed.

    Examples
    --------
    >>> import pandas as pd
    >>> t = pd.date_range("2026-03-01", periods=1440, freq="min", tz="UTC")
    >>> full = pd.DataFrame({"system_id": "a", "fetched_at": t})
    >>> half = pd.DataFrame({"system_id": "b", "fetched_at": t[:700]})
    >>> cov = daily_coverage(pd.concat([full, half]))
    >>> dict(zip(cov["system_id"], cov["status"]))
    {'a': 'ok', 'b': 'partial'}
    """
    need_columns(snapshots, ["system_id", time_col], what="daily_coverage")
    step = fixed_timedelta(poll_resolution, what="poll_resolution")
    expected = int(_DAY / step) if expected_polls is None else int(expected_polls)
    if expected <= 0:
        raise ValueError("expected_polls must be positive")
    if not 0 < ok_threshold_pct <= 100:
        raise ValueError("ok_threshold_pct must be in (0, 100]")

    reg = incident_registry(known_incidents)
    times = to_utc(snapshots[time_col], what=time_col)
    keep = times.notna().to_numpy()
    df = snapshots.loc[keep].copy()
    df[time_col] = times[keep].to_numpy()
    first_day = _as_day(start)
    if first_day is not None:
        df = df[df[time_col] >= pd.Timestamp(first_day, tz="UTC")]
    last_day = _as_day(end) or (df[time_col].max().date() if len(df) else None)
    if last_day is None:
        return _empty_coverage()
    df = df[df[time_col] < pd.Timestamp(last_day, tz="UTC") + _DAY]
    if df.empty:
        return _empty_coverage()

    gaps = find_collector_gaps(df, min_gap=min_collector_gap, known=reg, time_col=time_col)
    gap_intervals: list[_Interval] = list(zip(gaps["start_utc"], gaps["end_utc"], strict=True))

    both_zero = _both_zero(df)
    work = pd.DataFrame(
        {
            "system_id": df["system_id"].astype(str).to_numpy(),
            "day": df[time_col].dt.date.to_numpy(),
            "slot": df[time_col].dt.floor(step).to_numpy(),
            "zero": both_zero.to_numpy() if both_zero is not None else False,
        }
    )
    per_poll = work.groupby(["system_id", "day", "slot"], sort=False).size().rename("n")
    polls = per_poll.groupby(level=["system_id", "day"]).agg(n_polls="size", median_rows="median")
    rows_per_day = work.groupby(["system_id", "day"], sort=False).agg(
        rows=("slot", "size"), zeros=("zero", "sum")
    )
    observed = polls.join(rows_per_day)

    out_rows: list[dict[str, Any]] = []
    for system, sub in observed.groupby(level="system_id", sort=True):
        days = sub.droplevel("system_id")
        d = min(days.index)
        collector = gap_intervals + _intervals(reg, "outage_collector", str(system))
        operator = _intervals(reg, "outage_operator", str(system))
        while d <= last_day:
            t0 = pd.Timestamp(d, tz="UTC")
            n_polls, median_rows, share = 0, None, None
            if d in days.index:
                row = days.loc[d]
                n_polls, median_rows = int(row["n_polls"]), float(row["median_rows"])
                if both_zero is not None and row["rows"]:
                    share = round(100 * float(row["zeros"]) / float(row["rows"]), 2)
            pct = round(100 * min(n_polls, expected) / expected, 1)
            if pct >= ok_threshold_pct:
                status = STATUS_OK
            elif _overlaps(collector, t0, t0 + _DAY):
                status = STATUS_OUTAGE_COLLECTOR
            elif n_polls == 0 or _overlaps(operator, t0, t0 + _DAY):
                status = STATUS_OUTAGE_OPERATOR
            else:
                status = STATUS_PARTIAL
            out_rows.append(
                {
                    "date_utc": d,
                    "system_id": system,
                    "expected_polls": expected,
                    "actual_polls": n_polls,
                    "completeness_pct": pct,
                    "units_reporting_median": median_rows,
                    "both_zero_pct": share,
                    "status": status,
                }
            )
            d += dt.timedelta(days=1)
    out = pd.DataFrame(out_rows, columns=COVERAGE_COLUMNS)
    out["expected_polls"] = out["expected_polls"].astype("int64")
    out["actual_polls"] = out["actual_polls"].astype("int64")
    for c in ("completeness_pct", "units_reporting_median", "both_zero_pct"):
        out[c] = out[c].astype("float64")
    _log.info("coverage: %d system-days, %s", len(out), out["status"].value_counts().to_dict())
    return out


def find_silent_feeds(coverage: pd.DataFrame) -> pd.DataFrame:
    """Runs of consecutive ``outage_operator`` days per system: feeds that went silent.

    The collection was running (otherwise the days would be ``outage_collector``), yet the
    operator's feed gave nothing. A run that reaches the last day of ``coverage`` is *ongoing*
    (``end_utc`` is ``NaT``).

    Returns
    -------
    pandas.DataFrame
        ``system_id, start_utc, end_utc, n_days``.

    Examples
    --------
    >>> import pandas as pd
    >>> cov = pd.DataFrame({
    ...     "date_utc": pd.to_datetime(["2026-03-01", "2026-03-02", "2026-03-03"]).date,
    ...     "system_id": "a",
    ...     "status": ["ok", "outage_operator", "outage_operator"]})
    >>> silent = find_silent_feeds(cov)
    >>> int(silent.loc[0, "n_days"]), bool(pd.isna(silent.loc[0, "end_utc"]))
    (2, True)
    """
    need_columns(coverage, ["date_utc", "system_id", "status"], what="find_silent_feeds")
    out: list[dict[str, Any]] = []
    if len(coverage):
        last = max(coverage["date_utc"])
        for system, sub in coverage.sort_values("date_utc").groupby("system_id", sort=True):
            run: list[dt.date] = []
            days = list(zip(sub["date_utc"], sub["status"], strict=True))
            for i, (d, status) in enumerate(days):
                silent = status == STATUS_OUTAGE_OPERATOR
                if silent:
                    run.append(d)
                if run and (not silent or i == len(days) - 1):
                    ongoing = silent and run[-1] == last
                    out.append(
                        {
                            "system_id": system,
                            "start_utc": pd.Timestamp(run[0], tz="UTC"),
                            "end_utc": pd.NaT
                            if ongoing
                            else pd.Timestamp(run[-1], tz="UTC") + _DAY,
                            "n_days": len(run),
                        }
                    )
                    run = []
    res = pd.DataFrame(out, columns=["system_id", "start_utc", "end_utc", "n_days"])
    res["start_utc"] = pd.to_datetime(res["start_utc"], utc=True)
    res["end_utc"] = pd.to_datetime(res["end_utc"], utc=True)
    return res


def _fmt_duration(delta: pd.Timedelta) -> str:
    hours = delta.total_seconds() / 3600
    return f"{hours:.1f} h" if hours < 48 else f"{hours / 24:.0f} days"


def detect_incidents(
    coverage: pd.DataFrame,
    snapshots: pd.DataFrame | None = None,
    *,
    known: pd.DataFrame | None = None,
    min_collector_gap: str | pd.Timedelta = DEFAULT_MIN_GAP,
    time_col: str = "fetched_at",
) -> pd.DataFrame:
    """The registry completed with what the data shows: collection gaps and silent feeds.

    Your declared incidents (``known``) come first. With ``snapshots``, every
    `find_collector_gaps` stretch is added as ``collector-gap-<start>`` (cause
    ``outage_collector``); every `find_silent_feeds` run is added as
    ``silent-<system>-<day>`` (cause ``outage_operator``). Identifiers are stable: running it
    again on the same data gives the same registry.
    """
    reg = incident_registry(known)
    rows: list[dict[str, Any]] = []
    if snapshots is not None:
        gaps = find_collector_gaps(
            snapshots, min_gap=min_collector_gap, known=reg, time_col=time_col
        )
        for g in gaps.itertuples(index=False):
            rows.append(
                {
                    "incident_id": f"collector-gap-{g.start_utc:%Y%m%dT%H%M}Z",
                    "start_utc": g.start_utc,
                    "end_utc": g.end_utc,
                    "scope": "all",
                    "cause": "outage_collector",
                    "summary": (
                        f"No snapshot from any system for {_fmt_duration(g.duration)} "
                        "(collection gap detected; cause not documented)."
                    ),
                }
            )
    for s in find_silent_feeds(coverage).itertuples(index=False):
        ongoing = pd.isna(s.end_utc)
        plural = "s" if s.n_days > 1 else ""
        rows.append(
            {
                "incident_id": f"silent-{s.system_id}-{s.start_utc:%Y%m%d}",
                "start_utc": s.start_utc,
                "end_utc": pd.NaT if ongoing else s.end_utc,
                "scope": s.system_id,
                "cause": "outage_operator",
                "summary": (
                    f"No snapshot from {s.system_id} for {s.n_days} day{plural}"
                    f"{' (ongoing)' if ongoing else ''} while the collection was running: "
                    "the operator's feed was silent or failing (detected)."
                ),
            }
        )
    both = pd.concat([reg, incident_registry(rows)], ignore_index=True)
    return incident_registry(both.drop_duplicates("incident_id"))


@dataclass(frozen=True)
class QualityReport:
    """What `assess` returns: the coverage table and the incident registry."""

    coverage: pd.DataFrame
    incidents: pd.DataFrame

    def summary(self) -> dict[str, Any]:
        """Counts of system-days per status, and of incidents per cause."""
        return {
            "system_days": int(len(self.coverage)),
            "days_by_status": {s: int((self.coverage["status"] == s).sum()) for s in STATUSES},
            "incidents_by_cause": {
                str(k): int(v) for k, v in self.incidents["cause"].value_counts().items()
            },
        }


def assess(
    snapshots: pd.DataFrame,
    *,
    known_incidents: pd.DataFrame | None = None,
    time_col: str = "fetched_at",
    **coverage_options: Any,
) -> QualityReport:
    """Coverage and incidents in one call: `daily_coverage` then `detect_incidents`.

    ``coverage_options`` are the options of `daily_coverage` (``expected_polls``,
    ``ok_threshold_pct``, ``end`` ...).

    Examples
    --------
    >>> import pandas as pd
    >>> t = pd.date_range("2026-03-01", periods=1440, freq="min", tz="UTC")
    >>> report = assess(pd.DataFrame({"system_id": "demo", "fetched_at": t}))
    >>> report.summary()["days_by_status"]["ok"]
    1
    """
    cov = daily_coverage(
        snapshots, known_incidents=known_incidents, time_col=time_col, **coverage_options
    )
    inc = detect_incidents(
        cov,
        snapshots,
        known=known_incidents,
        min_collector_gap=coverage_options.get("min_collector_gap", DEFAULT_MIN_GAP),
        time_col=time_col,
    )
    return QualityReport(cov, inc)


# --------------------------------------------------------------------------------------
# Row-level indicators
# --------------------------------------------------------------------------------------


def _period_key(times: pd.Series, period: str) -> pd.Series:
    utc = times.dt.tz_convert("UTC")
    if period == "M":
        return utc.dt.year * 100 + utc.dt.month
    if period == "D":
        return utc.dt.year * 10000 + utc.dt.month * 100 + utc.dt.day
    if period == "all":
        return pd.Series(0, index=times.index)
    raise ValueError(f"period must be 'M', 'D' or 'all', got {period!r}")


def _period_start(key: int, period: str) -> pd.Timestamp:
    if period == "M":
        return pd.Timestamp(year=key // 100, month=key % 100, day=1, tz="UTC")
    if period == "D":
        return pd.Timestamp(year=key // 10000, month=key // 100 % 100, day=key % 100, tz="UTC")
    return pd.Timestamp(0, tz="UTC")


def field_unsupported_by_operator(
    df: pd.DataFrame,
    *,
    columns: tuple[str, ...] = _COUNT_COLS,
    period: str = "M",
    time_col: str = "fetched_at",
) -> pd.DataFrame:
    """Fields an operator does not publish: ``0`` in every non-empty value of the period.

    A system with no docks reports ``num_docks_available = 0`` everywhere. If every non-empty
    value of a column is ``0`` for a system over a ``period`` (a UTC month, ``"M"``, by default;
    ``"D"`` a day; ``"all"`` the whole frame), the column carries no information.

    Returns
    -------
    pandas.DataFrame
        ``system_id, period_start_utc, field``, one row per unsupported (system, period, field).

    Examples
    --------
    >>> import pandas as pd
    >>> df = pd.DataFrame({
    ...     "system_id": "a", "fetched_at": pd.to_datetime(["2026-03-01T00:00Z"] * 3),
    ...     "num_bikes_available": [3, 0, 5], "num_docks_available": [0, 0, 0]})
    >>> field_unsupported_by_operator(df)["field"].tolist()
    ['num_docks_available']
    """
    need_columns(df, ["system_id", time_col], what="field_unsupported_by_operator")
    key = _period_key(to_utc(df[time_col], what=time_col), period)
    rows = []
    for col in (c for c in columns if c in df.columns):
        frame = pd.DataFrame(
            {
                "system_id": df["system_id"].astype(str),
                "key": key,
                "v": pd.to_numeric(df[col], errors="coerce"),
            }
        ).dropna(subset=["v"])
        if frame.empty:
            continue
        frame["z"] = frame["v"] == 0
        agg = frame.groupby(["system_id", "key"], sort=True).agg(n=("v", "size"), z=("z", "sum"))
        for (system, k), _ in agg[agg["n"] == agg["z"]].iterrows():
            rows.append(
                {
                    "system_id": system,
                    "period_start_utc": _period_start(int(k), period),
                    "field": col,
                }
            )
    out = pd.DataFrame(rows, columns=["system_id", "period_start_utc", "field"])
    out["period_start_utc"] = pd.to_datetime(out["period_start_utc"], utc=True)
    return out.sort_values(["system_id", "period_start_utc", "field"]).reset_index(drop=True)


def add_quality_indicators(
    df: pd.DataFrame,
    *,
    capacity: pd.DataFrame | None = None,
    period: str = "M",
    all_zero_share: float = DEFAULT_ALL_ZERO_SHARE,
    mask_unsupported: bool = True,
    time_col: str = "fetched_at",
) -> pd.DataFrame:
    """Add the three ambiguity indicators to station-status rows (a copy; no row is removed).

    ``field_unsupported_by_operator``
        ``<NA>``, or the comma-separated fields the operator does not publish in the row's
        period (see `field_unsupported_by_operator`). With ``mask_unsupported`` (the
        default) those columns are set to missing in the returned frame, so a column of
        placeholders is not mistaken for data.
    ``both_zero_suspect``
        ``True`` for a row with zero bikes, zero free docks and a positive capacity; ``False``
        when its counts say otherwise; ``<NA>`` when a count or the capacity is missing (so also
        for a masked column or an unknown capacity).
    ``network_all_zero_anomaly``
        ``True`` when, in the row's poll (system and time), more than ``all_zero_share`` of all
        rows are at zero on every field the operator publishes; ``<NA>`` when it publishes
        neither field.

    Parameters
    ----------
    df : pandas.DataFrame
        ``system_id``, ``station_id``, ``time_col`` and the two count columns.
    capacity : pandas.DataFrame, optional
        ``station_id`` and ``capacity`` (and ``system_id`` when ids repeat across systems). If
        omitted, a ``capacity`` column of ``df`` is used.

    Examples
    --------
    >>> import pandas as pd
    >>> t = pd.to_datetime(["2026-03-01T10:00Z"] * 3)
    >>> df = pd.DataFrame({
    ...     "system_id": "a", "station_id": ["s1", "s2", "s3"], "fetched_at": t,
    ...     "num_bikes_available": [0, 4, 2], "num_docks_available": [0, 6, 0],
    ...     "capacity": [10, 10, 10]})
    >>> add_quality_indicators(df)["both_zero_suspect"].tolist()
    [True, False, False]
    """
    need_columns(df, ["system_id", "station_id", time_col], what="add_quality_indicators")
    if not 0 < all_zero_share <= 1:
        raise ValueError("all_zero_share must be in (0, 1]")
    out = df.copy()
    system = out["system_id"].astype(str)
    times = to_utc(out[time_col], what=time_col)
    present = [c for c in _COUNT_COLS if c in out.columns]
    key = _period_key(times, period)
    raw = {c: pd.to_numeric(out[c], errors="coerce") for c in present}

    unsupported = field_unsupported_by_operator(
        out, columns=tuple(present), period=period, time_col=time_col
    )
    muted: dict[str, pd.Series] = {}
    names: list[pd.Series] = []
    for col in present:
        sub = unsupported[unsupported["field"] == col]
        starts = _period_key(sub["period_start_utc"], period)
        pairs = set(zip(sub["system_id"], starts, strict=True))
        is_muted = pd.Series(
            [(s, int(k)) in pairs for s, k in zip(system, key, strict=True)],
            index=out.index,
            dtype=bool,
        )
        muted[col] = is_muted
        names.append(pd.Series(np.where(is_muted, col, ""), index=out.index, dtype="object"))
    flag_text = (
        pd.concat(names, axis=1).apply(lambda r: ",".join(v for v in r if v), axis=1)
        if names
        else pd.Series("", index=out.index, dtype="object")
    )

    # A poll's zero share: rows at zero on every published field / all rows of the poll.
    if present:
        zero_row = pd.Series(True, index=out.index)
        nothing_published = pd.Series(True, index=out.index)
        for c in present:
            zero_row &= (raw[c] == 0).fillna(False).astype(bool) | muted[c]
            nothing_published &= muted[c]
        zero_row &= ~nothing_published
        poll = pd.DataFrame({"system_id": system, "t": times, "z": zero_row.astype(float)})
        share = poll.groupby(["system_id", "t"], sort=False)["z"].transform("mean")
        anomaly = (share > all_zero_share).astype("boolean")
        anomaly[nothing_published] = pd.NA
    else:
        anomaly = pd.Series(pd.NA, index=out.index, dtype="boolean")

    if mask_unsupported:
        for c in present:
            if muted[c].any():
                out[c] = out[c].astype("Float64" if out[c].dtype.kind == "f" else out[c].dtype)
                out[c] = out[c].mask(muted[c])

    cap: pd.Series | None = None
    if capacity is not None:
        need_columns(capacity, ["station_id", "capacity"], what="add_quality_indicators(capacity)")
        keys = ["system_id", "station_id"] if "system_id" in capacity.columns else ["station_id"]
        cmap = capacity[[*keys, "capacity"]].drop_duplicates(keys).copy()
        for k in keys:
            cmap[k] = cmap[k].astype(str)
        left = pd.DataFrame(
            {"system_id": system.to_numpy(), "station_id": out["station_id"].astype(str).to_numpy()}
        )
        cap = pd.Series(
            left.merge(cmap, on=keys, how="left")["capacity"].to_numpy(), index=out.index
        )
    elif "capacity" in out.columns:
        cap = out["capacity"]

    if len(present) == 2 and cap is not None:
        b = pd.to_numeric(out[present[0]], errors="coerce")
        d = pd.to_numeric(out[present[1]], errors="coerce")
        c = pd.to_numeric(cap, errors="coerce")
        suspect = pd.Series(((b == 0) & (d == 0) & (c > 0)).to_numpy(), index=out.index).astype(
            "boolean"
        )
        suspect[(b.isna() | d.isna() | c.isna()).to_numpy()] = pd.NA
    else:
        suspect = pd.Series(pd.NA, index=out.index, dtype="boolean")

    out["field_unsupported_by_operator"] = flag_text.replace("", pd.NA).astype("string")
    out["both_zero_suspect"] = suspect
    out["network_all_zero_anomaly"] = anomaly
    return out

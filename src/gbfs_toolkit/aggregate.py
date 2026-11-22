"""Station availability aggregated to 15 minutes, an hour or a day, with fixed definitions.

!!! warning "Experimental"
    Part of the experimental data-lake modules added in 2.1.0: names, parameters and output
    columns may change in a minor release (see the API policy).

Minute-level snapshots are too many to plot or to join; what an analysis usually needs is a
station-by-bucket table whose columns mean the same thing every time. :func:`aggregate_availability`
produces one, with these definitions (they will not change silently):

``n_obs``
    rows in the bucket, all of them. Nothing is dropped or de-duplicated here, so
    **the sum of ``n_obs`` over all buckets is the number of input rows**, at every frequency
    (:func:`check_conservation` verifies it, and :func:`aggregate_levels` does it for you);
``n_valid``
    rows that carry a bike count and are not flagged ``both_zero_suspect`` (see
    :mod:`gbfs_toolkit.quality`): the observations every other column is computed from;
``bikes_mean``, ``bikes_min``, ``bikes_max``, ``bikes_first``, ``bikes_last``
    the bike count over the valid rows (first and last in time order);
``docks_mean``, ``docks_min``
    the same for free docks (missing when the operator does not publish them);
``pct_empty``
    share of valid rows with no bike, in %;
``pct_full``
    share of valid rows where the station is full, in %: no free dock, or, when docks are
    not published and a ``capacity`` column exists, bikes at or above the capacity;
``pct_renting``
    share of valid rows where the station is renting, in %;
``pct_both_zero``
    share of **all** rows flagged ``both_zero_suspect``, in % (counted here, excluded
    elsewhere); missing if the frame carries no such column;
``movement_volume``
    sum of the absolute changes of the bike count between two consecutive valid rows of the
    same station that are at most ``max_pair_gap`` (90 s) apart, attributed to the bucket of
    the second. It estimates how many bikes moved; a rental and a return inside one poll
    cancel out and are invisible. It is a volume of movement, not a count of trips.

Buckets are aligned on UTC. With ``tz``, the local wall-clock start of each bucket and the UTC
offset are added, so a local-time analysis can group on them without recomputing the clock change.

Examples
--------
>>> import pandas as pd
>>> from gbfs_toolkit.aggregate import aggregate_availability
>>> t = pd.date_range("2026-03-01T08:00Z", periods=30, freq="min")
>>> snaps = pd.DataFrame({
...     "system_id": "demo", "station_id": "s1", "fetched_at": t,
...     "num_bikes_available": range(30), "num_docks_available": range(30, 0, -1)})
>>> agg = aggregate_availability(snaps, "15min")
>>> agg["n_obs"].tolist(), agg["bikes_first"].tolist(), agg["bikes_last"].tolist()
([15, 15], [0, 15], [14, 29])
>>> int(agg["n_obs"].sum()) == len(snaps)
True
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

import numpy as np
import pandas as pd

from gbfs_toolkit.core._common import fixed_timedelta, need_columns, to_utc
from gbfs_toolkit.core.errors import GBFSValidationError

__all__ = [
    "AGGREGATE_COLUMNS",
    "LEVELS",
    "aggregate_availability",
    "aggregate_levels",
    "check_conservation",
]

_log = logging.getLogger(__name__)

#: Output columns (``bucket_start_local`` and ``utc_offset_min`` only when ``tz`` is given).
AGGREGATE_COLUMNS: list[str] = [
    "system_id",
    "station_id",
    "bucket_start_utc",
    "bucket_start_local",
    "utc_offset_min",
    "n_obs",
    "n_valid",
    "bikes_mean",
    "bikes_min",
    "bikes_max",
    "bikes_first",
    "bikes_last",
    "docks_mean",
    "docks_min",
    "pct_empty",
    "pct_full",
    "pct_renting",
    "pct_both_zero",
    "movement_volume",
]

#: The three usual levels: name -> frequency.
LEVELS: dict[str, str] = {"15m": "15min", "1h": "1h", "1d": "1D"}

_KEYS = ["system_id", "station_id", "bucket_start_utc"]


def _zone_of(tz: str | Mapping[str, str] | None, systems: pd.Series) -> pd.Series | None:
    if tz is None:
        return None
    if isinstance(tz, str):
        return pd.Series(tz, index=systems.index)
    return systems.map(lambda s: tz.get(s, "UTC"))


def _num(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(np.nan, index=df.index, dtype="float64")
    return pd.to_numeric(df[col], errors="coerce").astype("float64")


def aggregate_availability(
    df: pd.DataFrame,
    freq: str = "15min",
    *,
    tz: str | Mapping[str, str] | None = None,
    max_pair_gap: str | pd.Timedelta = "90s",
    time_col: str = "fetched_at",
) -> pd.DataFrame:
    """Aggregate station-status rows to buckets of ``freq`` (see the module for the definitions).

    Parameters
    ----------
    df : pandas.DataFrame
        One row per station per poll: ``system_id``, ``station_id``, ``time_col`` and
        ``num_bikes_available``; optionally ``num_docks_available``, ``is_renting``,
        ``capacity`` and ``both_zero_suspect``. Duplicated rows are counted; de-duplicate
        first if your source can repeat a poll.
    freq : str, default "15min"
        A fixed-width frequency: ``"15min"``, ``"1h"``, ``"1D"`` or any other.
    tz : str or mapping, optional
        An IANA zone, or ``{system_id: zone}``, for the local columns.
    max_pair_gap : str or Timedelta, default "90s"
        Longest time between two rows still counted as consecutive for ``movement_volume``.

    Returns
    -------
    pandas.DataFrame
        One row per (system, station, bucket) that has at least one row, sorted; columns as in
        :data:`AGGREGATE_COLUMNS`.

    Raises
    ------
    ValueError
        For a calendar frequency (``"1ME"``) or an unparseable time.

    Examples
    --------
    >>> import pandas as pd
    >>> t = pd.to_datetime(["2026-03-01T08:00Z", "2026-03-01T08:01Z", "2026-03-01T08:02Z"])
    >>> df = pd.DataFrame({"system_id": "a", "station_id": "s", "fetched_at": t,
    ...                    "num_bikes_available": [5, 3, 4]})
    >>> row = aggregate_availability(df, "1h").iloc[0]
    >>> int(row["n_obs"]), float(row["bikes_mean"]), int(row["movement_volume"])
    (3, 4.0, 3)
    """
    need_columns(
        df,
        ["system_id", "station_id", time_col, "num_bikes_available"],
        what="aggregate_availability",
    )
    step = fixed_timedelta(freq, what="freq")
    gap = fixed_timedelta(max_pair_gap, what="max_pair_gap")
    t = to_utc(df[time_col], what=time_col)

    w = pd.DataFrame(
        {
            "system_id": df["system_id"].astype(str).to_numpy(),
            "station_id": df["station_id"].astype(str).to_numpy(),
            "t": t.reset_index(drop=True),
            "b": _num(df, "num_bikes_available").to_numpy(),
            "d": _num(df, "num_docks_available").to_numpy(),
        }
    )
    has_flag = "both_zero_suspect" in df.columns
    suspect = (
        df["both_zero_suspect"].fillna(False).astype(bool).to_numpy()
        if has_flag
        else np.zeros(len(df), bool)
    )
    w["suspect"] = suspect
    w["valid"] = (~suspect) & w["b"].notna().to_numpy()
    w["bucket_start_utc"] = w["t"].dt.floor(step)
    # Stable sort by time inside each station: first/last and consecutive pairs depend on it.
    w = w.assign(_pos=np.arange(len(w))).sort_values(
        ["system_id", "station_id", "t", "_pos"], kind="stable"
    )
    keep_valid = w["valid"]
    w["bv"] = w["b"].where(keep_valid)
    w["dv"] = w["d"].where(~w["suspect"])
    w["empty"] = (w["bv"] == 0).astype("float64").where(keep_valid)

    d_known = w["d"].notna()
    if "capacity" in df.columns:
        cap = _num(df, "capacity").reindex(w.index)
    else:
        cap = pd.Series(np.nan, index=w.index)
    full = pd.Series(np.nan, index=w.index)
    full = full.mask(d_known & keep_valid, (w["d"] == 0).astype("float64"))
    by_cap = (~d_known) & keep_valid & cap.notna()
    full = full.mask(by_cap, (w["b"] >= cap).astype("float64"))
    w["full"] = full
    if "is_renting" in df.columns:
        renting = pd.to_numeric(df["is_renting"].astype("Float64"), errors="coerce")
        w["renting"] = renting.reindex(w.index).astype("float64").where(keep_valid)
    else:
        w["renting"] = np.nan
    w["suspect_f"] = w["suspect"].astype("float64") if has_flag else np.nan

    g = w.groupby(["system_id", "station_id"], sort=False)
    prev_b, prev_t, prev_ok = (
        g["b"].shift(1),
        g["t"].shift(1),
        g["valid"].shift(1, fill_value=False),
    )
    pair = w["valid"] & prev_ok.astype(bool) & ((w["t"] - prev_t) <= gap)
    w["move"] = (w["b"] - prev_b).abs().where(pair)

    grouped = w.groupby(_KEYS, sort=True)
    out = grouped.agg(
        n_obs=("t", "size"),
        n_valid=("bv", "count"),
        bikes_mean=("bv", "mean"),
        bikes_min=("bv", "min"),
        bikes_max=("bv", "max"),
        bikes_first=("bv", "first"),
        bikes_last=("bv", "last"),
        docks_mean=("dv", "mean"),
        docks_min=("dv", "min"),
        pct_empty=("empty", "mean"),
        pct_full=("full", "mean"),
        pct_renting=("renting", "mean"),
        pct_both_zero=("suspect_f", "mean"),
        movement_volume=("move", lambda s: s.sum(min_count=1)),
    ).reset_index()
    for c in ("pct_empty", "pct_full", "pct_renting", "pct_both_zero"):
        out[c] = out[c] * 100
    for c in (
        "bikes_min",
        "bikes_max",
        "bikes_first",
        "bikes_last",
        "docks_min",
        "movement_volume",
    ):
        out[c] = out[c].round().astype("Int64")
    out["n_obs"] = out["n_obs"].astype("int64")
    out["n_valid"] = out["n_valid"].astype("int64")

    zone = _zone_of(tz, out["system_id"])
    if zone is not None:
        local = []
        offset = []
        for start, z in zip(out["bucket_start_utc"], zone, strict=True):
            here = start.tz_convert(z)
            local.append(here.tz_localize(None))
            offset.append(int(here.utcoffset().total_seconds() // 60))
        out["bucket_start_local"] = pd.to_datetime(local)
        out["utc_offset_min"] = pd.array(offset, dtype="Int16")
    cols = [c for c in AGGREGATE_COLUMNS if c in out.columns]
    _log.info("aggregate: %d rows -> %d buckets of %s", len(df), len(out), freq)
    return out[cols].reset_index(drop=True)


def check_conservation(aggregated: pd.DataFrame, source: pd.DataFrame) -> None:
    """Raise ``GBFSValidationError`` unless the buckets hold exactly the source rows.

    The sum of ``n_obs`` must equal ``len(source)``: an aggregate that lost or invented an
    observation is wrong whatever its means look like.

    Examples
    --------
    >>> import pandas as pd
    >>> check_conservation(pd.DataFrame({"n_obs": [15, 15]}), pd.DataFrame({"x": range(30)}))
    """
    got, want = int(aggregated["n_obs"].sum()), int(len(source))
    if got != want:
        raise GBFSValidationError(
            f"aggregation does not conserve observations: sum of n_obs is {got}, source has {want} rows"
        )


def aggregate_levels(
    df: pd.DataFrame,
    *,
    levels: Mapping[str, str] | None = None,
    verify: bool = True,
    **options: object,
) -> dict[str, pd.DataFrame]:
    """The 15-minute, hourly and daily aggregates in one call, each checked for conservation.

    Returns ``{"15m": ..., "1h": ..., "1d": ...}`` (or the ``levels`` you give, name -> freq);
    ``options`` go to :func:`aggregate_availability`. With ``verify`` (the default) each level
    must conserve the observations, so the three tables describe the same rows.

    Examples
    --------
    >>> import pandas as pd
    >>> t = pd.date_range("2026-03-01T00:00Z", periods=200, freq="min")
    >>> df = pd.DataFrame({"system_id": "a", "station_id": "s", "fetched_at": t,
    ...                    "num_bikes_available": 3})
    >>> out = aggregate_levels(df)
    >>> {k: int(v["n_obs"].sum()) for k, v in out.items()}
    {'15m': 200, '1h': 200, '1d': 200}
    """
    result = {}
    for name, freq in (levels or LEVELS).items():
        agg = aggregate_availability(df, freq, **options)  # type: ignore[arg-type]
        if verify:
            check_conservation(agg, df)
        result[name] = agg
    return result

"""Readers for the trip files that operators publish, into one common schema.

!!! warning "Experimental"
    Part of the experimental data-lake modules added in 2.1.0: names, parameters and output
    columns may change in a minor release (see the API policy).

Several operators publish one row per trip as open data, each in its own shape. This module
reads the families below into the same table, `TRIP_COLUMNS`:

``lyft``
    the Lyft / Motivate family (Citi Bike, Divvy, Bluebikes, Bay Wheels, Capital Bikeshare,
    Nice Ride...): the current files (``ride_id, started_at, ended_at, start_station_id,
    start_lat ...``) and the older ones (``tripduration, starttime, stoptime, start station id
    ...``; ``trip_id, from_station_id ...``; ``Start date, Start station number ...``);
``urban_sharing``
    the Urban Sharing platform's files (Oslo, Bergen, Trondheim): ISO 8601 times with an
    offset, coordinates inline;
``bts``
    the Bicycle Transit Systems files (Indego, Metro Bike Share).

Anything else: describe the columns once with `TripFormat` and pass it as ``fmt``. No
format is guessed beyond these; in particular the module reads no format it has not been shown.

**Time zones are explicit.** Most files publish *local* wall-clock times without a zone, so
``tz`` (an IANA name such as ``"America/Chicago"``) is required for them: there is no default,
because UTC would be a silent mistake. Times come out tz-aware UTC. A local time that does not
exist (the hour skipped in spring) is moved to the first instant after the change and one that happens twice (the repeated
hour in autumn) is read as the second, standard-time occurrence; both are flagged in
``started_at_tz_flag`` / ``ended_at_tz_flag`` (``"nonexistent"``, ``"ambiguous"``), never
guessed silently.

**No personal data is carried over.** Birth year, gender and bike number are dropped, and the
common schema has no user identifier; ``member_type`` is only ``member`` or ``casual``.

Examples
--------
>>> import pandas as pd
>>> from gbfs_toolkit.trips import normalize_trips
>>> raw = pd.DataFrame({
...     "ride_id": ["r1"], "rideable_type": ["electric_bike"], "member_casual": ["member"],
...     "started_at": ["2025-07-04 08:00:00"], "ended_at": ["2025-07-04 08:12:30"],
...     "start_station_id": ["S1"], "end_station_id": ["S2"]})
>>> out = normalize_trips(raw, tz="America/New_York", network="demo")
>>> str(out.loc[0, "started_at"]), float(out.loc[0, "duration_s"])
('2025-07-04 12:00:00+00:00', 750.0)
"""

from __future__ import annotations

import io
import logging
import zipfile
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

__all__ = [
    "TRIP_COLUMNS",
    "FORMATS",
    "TripFormat",
    "detect_format",
    "normalize_trips",
    "iter_trips",
    "read_trips",
]

_log = logging.getLogger(__name__)

#: The common schema. ``network`` and ``source_file`` say where a row comes from;
#: ``ride_id`` is the operator's own trip identifier (never a user's).
TRIP_COLUMNS: list[str] = [
    "network",
    "ride_id",
    "started_at",
    "ended_at",
    "duration_s",
    "start_station_id",
    "start_station_name",
    "start_lat",
    "start_lng",
    "end_station_id",
    "end_station_name",
    "end_lat",
    "end_lng",
    "rideable_type",
    "member_type",
    "started_at_tz_flag",
    "ended_at_tz_flag",
    "source_file",
]
_TEXT = (
    "ride_id",
    "start_station_id",
    "start_station_name",
    "end_station_id",
    "end_station_name",
    "rideable_type",
    "member_type",
)
_COORDS = ("start_lat", "start_lng", "end_lat", "end_lng")


@dataclass(frozen=True)
class TripFormat:
    """How the columns of one publisher's file map onto `TRIP_COLUMNS`.

    Parameters
    ----------
    name : str
        A label, for messages.
    columns : mapping
        ``{common column: [names it may have in the file]}``, compared case-insensitively and
        ignoring surrounding spaces. The first name present wins. Time columns ``started_at`` and
        ``ended_at`` are required; the others may be absent (they come out empty).
    times_have_offset : bool, default False
        ``True`` when the file's times carry their own offset (``...Z``, ``+02:00``): they are
        then converted to UTC and ``tz`` is not needed.
    duration_alias : sequence of str
        Columns that hold the duration, in seconds times ``duration_scale``.
    duration_scale : float, default 1.0
        Seconds per unit of the duration column (60 for minutes).
    recompute_duration : bool, default False
        Ignore the file's duration and compute it from the two times (use it when the unit of
        the published column is unreliable).
    member_map, rideable_map : mapping
        Value translations (lower case keys) for ``member_type`` and ``rideable_type``.
    member_rule : callable, optional
        A function from the raw membership value to ``"member"``, ``"casual"`` or ``None``,
        used instead of ``member_map``.

    Examples
    --------
    >>> fmt = TripFormat("mycity", {"started_at": ["debut"], "ended_at": ["fin"], "ride_id": ["id"]},
    ...                  times_have_offset=True)
    >>> import pandas as pd
    >>> normalize_trips(pd.DataFrame({"id": [1], "debut": ["2025-01-01T10:00:00+01:00"],
    ...                               "fin": ["2025-01-01T10:05:00+01:00"]}), fmt)["duration_s"].tolist()
    [300.0]
    """

    name: str
    columns: Mapping[str, Sequence[str]]
    times_have_offset: bool = False
    duration_alias: Sequence[str] = ()
    duration_scale: float = 1.0
    recompute_duration: bool = False
    member_map: Mapping[str, str] = field(default_factory=dict)
    rideable_map: Mapping[str, str] = field(default_factory=dict)
    member_rule: Callable[[Any], str | None] | None = None

    def __post_init__(self) -> None:
        unknown = set(self.columns) - set(TRIP_COLUMNS)
        if unknown:
            raise ValueError(
                f"TripFormat {self.name!r}: unknown common column(s) {sorted(unknown)}"
            )
        missing = {"started_at", "ended_at"} - set(self.columns)
        if missing:
            raise ValueError(f"TripFormat {self.name!r}: columns must name {sorted(missing)}")


_MEMBERS = {"subscriber": "member", "member": "member", "customer": "casual", "casual": "casual"}


def _passholder(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    low = value.lower()
    return "casual" if any(k in low for k in ("walk", "day", "one")) else "member"


FORMATS: dict[str, TripFormat] = {
    "lyft": TripFormat(
        "lyft",
        {
            "ride_id": ["ride_id", "trip_id", "trip id"],
            "started_at": [
                "started_at",
                "start_time",
                "starttime",
                "start date",
                "01 - rental details local start time",
            ],
            "ended_at": [
                "ended_at",
                "end_time",
                "stoptime",
                "end date",
                "02 - rental details local end time",
            ],
            "start_station_id": [
                "start_station_id",
                "start station id",
                "from_station_id",
                "start station number",
                "03 - rental start station id",
            ],
            "start_station_name": [
                "start_station_name",
                "start station name",
                "from_station_name",
                "start station",
                "03 - rental start station name",
            ],
            "end_station_id": [
                "end_station_id",
                "end station id",
                "to_station_id",
                "end station number",
            ],
            "end_station_name": [
                "end_station_name",
                "end station name",
                "to_station_name",
                "end station",
            ],
            "start_lat": ["start_lat", "start station latitude"],
            "start_lng": ["start_lng", "start station longitude"],
            "end_lat": ["end_lat", "end station latitude"],
            "end_lng": ["end_lng", "end station longitude"],
            "rideable_type": ["rideable_type", "bike type"],
            "member_type": ["member_casual", "usertype", "user type", "member type"],
        },
        duration_alias=("tripduration", "duration", "duration_sec"),
        member_map=_MEMBERS,
    ),
    "urban_sharing": TripFormat(
        "urban_sharing",
        {
            "started_at": ["started_at"],
            "ended_at": ["ended_at"],
            "start_station_id": ["start_station_id"],
            "start_station_name": ["start_station_name"],
            "start_lat": ["start_station_latitude"],
            "start_lng": ["start_station_longitude"],
            "end_station_id": ["end_station_id"],
            "end_station_name": ["end_station_name"],
            "end_lat": ["end_station_latitude"],
            "end_lng": ["end_station_longitude"],
        },
        times_have_offset=True,
        duration_alias=("duration",),
    ),
    "bts": TripFormat(
        "bts",
        {
            "ride_id": ["trip_id"],
            "started_at": ["start_time"],
            "ended_at": ["end_time"],
            "start_station_id": ["start_station"],
            "end_station_id": ["end_station"],
            "start_lat": ["start_lat"],
            "start_lng": ["start_lon"],
            "end_lat": ["end_lat"],
            "end_lng": ["end_lon"],
            "rideable_type": ["bike_type"],
            "member_type": ["passholder_type"],
        },
        recompute_duration=True,  # the published `duration` changes unit between years
        rideable_map={"electric": "electric_bike", "standard": "classic_bike"},
        member_rule=_passholder,
    ),
}


def _lookup(df: pd.DataFrame) -> dict[str, str]:
    return {str(c).lower().strip(): c for c in df.columns}


def _present(fmt: TripFormat, lower: Mapping[str, str]) -> dict[str, str]:
    found = {}
    for common, aliases in fmt.columns.items():
        col = next((lower[a.lower().strip()] for a in aliases if a.lower().strip() in lower), None)
        if col is not None:
            found[common] = col
    return found


def detect_format(columns: Sequence[str]) -> str | None:
    """The name of the `FORMATS` entry whose columns these are, or ``None``.

    Examples
    --------
    >>> detect_format(["ride_id", "started_at", "ended_at", "start_lat", "start_lng"])
    'lyft'
    >>> detect_format(["started_at", "ended_at", "duration", "start_station_latitude"])
    'urban_sharing'
    >>> detect_format(["trip_id", "start_time", "end_time", "start_lon", "passholder_type"])
    'bts'
    >>> detect_format(["a", "b"]) is None
    True
    """
    low = {str(c).lower().strip() for c in columns}
    if {"started_at", "start_station_latitude"} <= low:
        return "urban_sharing"
    if "start_lon" in low and "start_time" in low:
        return "bts"
    lyft = FORMATS["lyft"]
    has_start = any(a.lower() in low for a in lyft.columns["started_at"])
    has_end = any(a.lower() in low for a in lyft.columns["ended_at"])
    return "lyft" if has_start and has_end else None


def _id_text(series: pd.Series) -> pd.Series:
    """Identifiers as text: ``5905.0`` read as a float becomes ``"5905"``, not ``"5905.0"``."""
    if pd.api.types.is_float_dtype(series):
        whole = series.dropna() % 1 == 0
        if whole.all():
            return series.astype("Int64").astype("string")
    return series.astype("string")


def _localize(naive: pd.Series, tz: str) -> tuple[pd.Series, pd.Series]:
    """Local wall-clock times to UTC, with a flag for the times a clock change makes odd."""
    try:
        first = naive.dt.tz_localize(tz, ambiguous=False, nonexistent="shift_forward")
        nonexistent = (
            naive.dt.tz_localize(tz, ambiguous=False, nonexistent="NaT").isna() & naive.notna()
        )
        ambiguous = (
            naive.dt.tz_localize(tz, ambiguous="NaT", nonexistent="shift_forward").isna()
            & naive.notna()
        )
    except Exception as exc:  # noqa: BLE001 (unknown zone: pytz and zoneinfo raise different types)
        if "NaT" in str(exc):
            raise
        raise ValueError(f"unknown or unusable time zone {tz!r}: {exc}") from exc
    flag = pd.Series(pd.NA, index=naive.index, dtype="string")
    flag = flag.mask(ambiguous, "ambiguous").mask(nonexistent, "nonexistent")
    return first.dt.tz_convert("UTC"), flag


def _strip_offset_naive(parsed: pd.Series) -> pd.Series:
    """Drop a zone that pandas attached by itself, keeping the wall clock."""
    return parsed.dt.tz_localize(None) if isinstance(parsed.dtype, pd.DatetimeTZDtype) else parsed


def normalize_trips(
    df: pd.DataFrame,
    fmt: str | TripFormat = "auto",
    *,
    tz: str | None = None,
    network: str | None = None,
    source_file: str | None = None,
) -> pd.DataFrame:
    """Rows of one publisher's file, in the common schema `TRIP_COLUMNS`.

    Parameters
    ----------
    df : pandas.DataFrame
        The file as read (any dtypes; ``dtype=str`` is the safest way to read it).
    fmt : str or TripFormat, default "auto"
        A key of `FORMATS`, a `TripFormat`, or ``"auto"`` to use
        `detect_format`.
    tz : str, optional
        IANA zone of the file's local times. Required unless the format's times carry an offset.
    network, source_file : str, optional
        Written into the output columns of the same name.

    Returns
    -------
    pandas.DataFrame
        Rows without a start time are dropped (and counted in the log); nothing else is. A value
        the file does not carry is empty (``<NA>``/``NaN``), not guessed.

    Raises
    ------
    ValueError
        For an unknown or undetectable format, or a missing ``tz``.

    Examples
    --------
    >>> import pandas as pd
    >>> raw = pd.DataFrame({"tripduration": [600], "starttime": ["2020-03-08 02:30:00"],
    ...                     "stoptime": ["2020-03-08 03:10:00"], "usertype": ["Subscriber"],
    ...                     "birth year": [1980], "gender": [1], "bikeid": [7]})
    >>> out = normalize_trips(raw, tz="America/New_York")
    >>> out.loc[0, "started_at_tz_flag"], out.loc[0, "member_type"], "gender" in out.columns
    ('nonexistent', 'member', False)
    """
    if isinstance(fmt, str):
        name = detect_format(list(df.columns)) if fmt == "auto" else fmt
        if name is None:
            raise ValueError(
                f"cannot tell the trip format from the columns {list(df.columns)[:8]}; "
                "pass fmt= (a key of FORMATS or a TripFormat)"
            )
        if name not in FORMATS:
            raise ValueError(f"unknown trip format {name!r}; known: {sorted(FORMATS)}")
        spec = FORMATS[name]
    else:
        spec = fmt
    if not spec.times_have_offset and tz is None:
        raise ValueError(
            f"format {spec.name!r} publishes local times without a zone: pass tz='Area/City' "
            "(for instance tz='America/Chicago')"
        )
    lower = _lookup(df)
    cols = _present(spec, lower)
    for required in ("started_at", "ended_at"):
        if required not in cols:
            raise ValueError(
                f"format {spec.name!r}: no column for {required} in {list(df.columns)[:10]}"
            )

    out = pd.DataFrame(index=df.index)
    for common in TRIP_COLUMNS:
        if common in cols and common not in ("started_at", "ended_at"):
            out[common] = df[cols[common]]
    for common in _TEXT:
        out[common] = (
            _id_text(out[common])
            if common in out
            else pd.Series(pd.NA, index=df.index, dtype="string")
        )
    for common in _COORDS:
        out[common] = (
            pd.to_numeric(out[common], errors="coerce").astype("float64")
            if common in out
            else pd.Series(np.nan, index=df.index, dtype="float64")
        )

    raw_t = {
        k: pd.to_datetime(df[cols[k]], errors="coerce", format="mixed", utc=spec.times_have_offset)
        for k in ("started_at", "ended_at")
    }
    if spec.times_have_offset:
        started, ended = raw_t["started_at"], raw_t["ended_at"]
        flag_s = flag_e = pd.Series(pd.NA, index=df.index, dtype="string")
    else:
        assert tz is not None
        started, flag_s = _localize(_strip_offset_naive(raw_t["started_at"]), tz)
        ended, flag_e = _localize(_strip_offset_naive(raw_t["ended_at"]), tz)
    out["started_at"], out["ended_at"] = started, ended
    out["started_at_tz_flag"], out["ended_at_tz_flag"] = flag_s, flag_e

    computed = (ended - started).dt.total_seconds()
    published = next((lower[a.lower()] for a in spec.duration_alias if a.lower() in lower), None)
    if published is not None and not spec.recompute_duration:
        seconds = pd.to_numeric(df[published], errors="coerce") * spec.duration_scale
        out["duration_s"] = seconds.where(seconds.notna(), computed).astype("float64")
    else:
        out["duration_s"] = computed.astype("float64")

    if "member_type" in cols:
        raw_member = df[cols["member_type"]]
        if spec.member_rule is not None:
            member = raw_member.map(spec.member_rule)
        else:
            low = raw_member.astype("string").str.lower().str.strip()
            member = low.map(dict(spec.member_map)).fillna(low) if spec.member_map else low
        out["member_type"] = member.astype("string")
    if "rideable_type" in cols and spec.rideable_map:
        low = out["rideable_type"].str.lower().str.strip()
        out["rideable_type"] = low.map(dict(spec.rideable_map)).fillna(low).astype("string")

    out["network"] = pd.Series(network, index=df.index, dtype="string")
    out["source_file"] = pd.Series(source_file, index=df.index, dtype="string")
    dropped = int(out["started_at"].isna().sum())
    if dropped:
        _log.warning("%d row(s) without a readable start time were dropped", dropped)
    return out.loc[out["started_at"].notna(), TRIP_COLUMNS].reset_index(drop=True)


def _csv_chunks(source: Any, label: str, chunksize: int) -> Iterator[tuple[str, pd.DataFrame]]:
    """Chunks of every CSV in a file, an open binary stream or a (nested) zip, as text."""
    if isinstance(source, (str, Path)):
        path = Path(source)
        if path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as zf:
                yield from _zip_chunks(zf, f"{path.name}::", chunksize)
            return
        for chunk in pd.read_csv(
            path, dtype=str, chunksize=chunksize, keep_default_na=False, na_values=[""]
        ):
            yield path.name, chunk
        return
    for chunk in pd.read_csv(
        source, dtype=str, chunksize=chunksize, keep_default_na=False, na_values=[""]
    ):
        yield label, chunk


def _zip_chunks(
    zf: zipfile.ZipFile, prefix: str, chunksize: int
) -> Iterator[tuple[str, pd.DataFrame]]:
    for name in zf.namelist():
        low = name.lower()
        if name.endswith("/") or "__macosx" in low:
            continue
        if low.endswith(".csv"):
            with zf.open(name) as fh:
                for chunk in pd.read_csv(
                    fh, dtype=str, chunksize=chunksize, keep_default_na=False, na_values=[""]
                ):
                    yield prefix + name, chunk
        elif low.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(zf.read(name))) as inner:
                yield from _zip_chunks(inner, f"{prefix}{name}::", chunksize)


def iter_trips(
    path: str | Path | Any,
    fmt: str | TripFormat = "auto",
    *,
    tz: str | None = None,
    network: str | None = None,
    chunksize: int = 500_000,
) -> Iterator[pd.DataFrame]:
    """Read a trip CSV (or a zip of CSVs, nested zips included) chunk by chunk, normalised.

    Memory stays bounded by ``chunksize`` rows, which matters for a year of a large system.
    ``source_file`` records the file (``archive.zip::inner.csv`` inside a zip). Arguments are
    those of `normalize_trips`.

    Examples
    --------
    >>> import io
    >>> csv = io.BytesIO(b"ride_id,started_at,ended_at\\nr1,2025-01-01 10:00:00,2025-01-01 10:05:00\\n")
    >>> [len(c) for c in iter_trips(csv, tz="UTC", network="demo")]
    [1]
    """
    for label, chunk in _csv_chunks(path, "<stream>", chunksize):
        yield normalize_trips(chunk, fmt, tz=tz, network=network, source_file=label)


def read_trips(
    path: str | Path | Any,
    fmt: str | TripFormat = "auto",
    *,
    tz: str | None = None,
    network: str | None = None,
    chunksize: int = 500_000,
) -> pd.DataFrame:
    """All the trips of a CSV or zip file as one frame (see `iter_trips` for huge files).

    Examples
    --------
    >>> import io
    >>> csv = io.BytesIO(b"trip_id,start_time,end_time,start_lat,start_lon,passholder_type\\n"
    ...                  b"1,2025-01-01 10:00:00,2025-01-01 10:05:00,39.9,-75.1,Walk-up\\n")
    >>> trips = read_trips(csv, tz="America/New_York")
    >>> trips.loc[0, "member_type"], float(trips.loc[0, "duration_s"])
    ('casual', 300.0)
    """
    frames = list(iter_trips(path, fmt, tz=tz, network=network, chunksize=chunksize))
    if not frames:
        return pd.DataFrame(columns=TRIP_COLUMNS)
    return pd.concat(frames, ignore_index=True)

"""A polite collector of GBFS station and vehicle snapshots, written one file per day.

!!! warning "Experimental"
    Part of the experimental data-lake modules added in 2.1.0: names, parameters and output
    columns may change in a minor release (see the API policy).

Nothing here runs in the background: you call :meth:`Collector.poll_once`, or
:meth:`Collector.run` (a loop in your own process, bounded by a duration or a number of
iterations), or the ``gbfs collect`` command. What it does, and refuses to do:

* **It identifies itself.** A ``user_agent`` is required (there is no default): give one that
  tells the operator whom to write to, for example ``"my-lab-gbfs/1.0 (mailto:me@example.org)"``.
* **It respects the feed's ``ttl``.** A GBFS document says how long it stays fresh; the
  collector will not ask again before that, nor before ``min_interval``. A feed that answers
  with an error is left alone for longer each time (exponential back-off, capped), and HTTP
  retries honour ``Retry-After``.
* **It never invents a value.** A field the feed leaves out is stored empty, typed
  (``Int64`` for counts, ``boolean`` for flags, ``float64`` for coordinates), never ``0`` nor
  ``True``. A station that publishes nothing must not look like an empty or an open station.
  (This is stricter than :func:`gbfs_toolkit.to_canonical_station_status`, which defaults a
  missing ``is_renting`` to ``True``.)
* **It writes atomically**, one Parquet file per system and UTC day::

      <out_dir>/station_status/<system_id>/2026-03-01.parquet
      <out_dir>/vehicle_status/<system_id>/2026-03-01.parquet

  (a day file is rewritten as a whole at each poll, which is simple and safe for a few hundred
  stations at a one-minute cadence; for much larger volumes use the lake of
  :mod:`gbfs_toolkit.store`.)

Networking needs the ``fetch`` extra and Parquet the ``parquet`` extra. For offline work,
pass ``get_json`` (a ``url -> dict`` function): the tests of this module use a local server.

Examples
--------
>>> import tempfile
>>> from gbfs_toolkit.collect import Collector, read_collected
>>> docs = {
...     "https://example.org/gbfs.json": {"version": "2.3", "data": {"en": {"feeds": [
...         {"name": "station_status", "url": "https://example.org/status.json"}]}}},
...     "https://example.org/status.json": {"ttl": 0, "data": {"stations": [
...         {"station_id": "7", "num_bikes_available": 4, "is_renting": 1},
...         {"station_id": "8"}]}},
... }
>>> with tempfile.TemporaryDirectory() as out:
...     c = Collector({"demo": "https://example.org/gbfs.json"}, out,
...                   user_agent="docs-example/1.0", get_json=docs.__getitem__, min_interval=0)
...     outcome = c.poll_once()
...     snaps = read_collected(out)
>>> outcome["outcome"].tolist(), snaps["num_bikes_available"].isna().tolist()
(['collected'], [False, True])
"""

from __future__ import annotations

import logging
import threading
import time
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from gbfs_toolkit.core._common import atomic_write, require_pyarrow, to_utc
from gbfs_toolkit.core.errors import GBFSError, GBFSFetchError
from gbfs_toolkit.core.utils import parse_gbfs_timestamp
from gbfs_toolkit.io.normalize import _records

__all__ = [
    "FEED_KINDS",
    "METADATA_FEEDS",
    "OUTCOMES",
    "Collector",
    "parse_station_status",
    "parse_vehicle_status",
    "read_collected",
]

_log = logging.getLogger(__name__)

#: What can be collected. ``vehicle_status`` is read from ``vehicle_status`` (GBFS 3) or
#: ``free_bike_status`` (GBFS 2).
FEED_KINDS: tuple[str, ...] = ("station_status", "vehicle_status")
_FEED_NAMES = {
    "station_status": ("station_status",),
    "vehicle_status": ("vehicle_status", "free_bike_status"),
}
#: The outcome of one (system, feed) at one poll.
OUTCOMES: tuple[str, ...] = (
    "collected",  # rows written
    "empty",  # the feed answered but listed nothing
    "skipped_ttl",  # asked too soon: the feed is still fresh
    "skipped_backoff",  # a recent failure: waiting before trying again
    "unavailable",  # the system does not publish this feed
    "failed",  # network, HTTP or parsing error (logged)
)
_REDISCOVER_AFTER = 3600.0
#: Slowly changing feeds that :meth:`Collector.poll_metadata` keeps a dated history of.
METADATA_FEEDS: tuple[str, ...] = (
    "system_information",
    "station_information",
    "vehicle_types",
    "system_pricing_plans",
    "system_regions",
)

_STATION_COLUMNS = [
    "system_id",
    "station_id",
    "fetched_at",
    "last_reported",
    "num_bikes_available",
    "num_docks_available",
    "is_renting",
    "is_returning",
    "is_installed",
]
_VEHICLE_COLUMNS = [
    "system_id",
    "vehicle_id",
    "fetched_at",
    "station_id",
    "vehicle_type_id",
    "lat",
    "lon",
    "is_disabled",
    "is_reserved",
]


def _missing(value: Any) -> bool:
    return value is None or (isinstance(value, float) and value != value)


def _int(value: Any) -> Any:
    if _missing(value):
        return pd.NA
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return pd.NA


def _flag(value: Any) -> Any:
    """A boolean, or ``NA`` when the feed does not say. Never a guessed default."""
    if _missing(value):
        return pd.NA
    if isinstance(value, str):
        low = value.strip().lower()
        if low in ("true", "1", "yes"):
            return True
        if low in ("false", "0", "no"):
            return False
        return pd.NA
    return bool(value)


def _float(value: Any) -> float:
    if _missing(value):
        return float("nan")
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def _text(value: Any) -> Any:
    return pd.NA if _missing(value) else str(value)


def parse_station_status(
    doc: Mapping[str, Any], *, system_id: str, fetched_at: pd.Timestamp | None = None
) -> pd.DataFrame:
    """A ``station_status`` document as one row per station, missing values left missing.

    Reads the GBFS 2 and 3 field names (``num_vehicles_available`` and
    ``vehicle_docks_available`` stand in for the 2.x names). Counts are ``Int64``, flags
    ``boolean``, ``last_reported`` and ``fetched_at`` tz-aware UTC.

    Examples
    --------
    >>> doc = {"data": {"stations": [{"station_id": "a", "num_bikes_available": 2},
    ...                              {"station_id": "b", "is_renting": False}]}}
    >>> out = parse_station_status(doc, system_id="demo")
    >>> out["is_renting"].tolist()[0] is pd.NA, out["is_renting"].tolist()[1]
    (True, False)
    >>> out["num_bikes_available"].isna().tolist()
    [False, True]
    """
    when = pd.Timestamp.now(tz="UTC") if fetched_at is None else to_utc([fetched_at]).iloc[0]
    rows = []
    for s in _records(doc.get("data", doc), "stations"):
        bikes = s.get("num_bikes_available")
        docks = s.get("num_docks_available")
        rows.append(
            {
                "system_id": system_id,
                "station_id": _text(s.get("station_id")),
                "fetched_at": when,
                "last_reported": parse_gbfs_timestamp(s.get("last_reported")),
                "num_bikes_available": _int(
                    bikes if not _missing(bikes) else s.get("num_vehicles_available")
                ),
                "num_docks_available": _int(
                    docks if not _missing(docks) else s.get("vehicle_docks_available")
                ),
                "is_renting": _flag(s.get("is_renting")),
                "is_returning": _flag(s.get("is_returning")),
                "is_installed": _flag(s.get("is_installed")),
            }
        )
    df = pd.DataFrame(rows, columns=_STATION_COLUMNS)
    for c in ("num_bikes_available", "num_docks_available"):
        df[c] = df[c].astype("Int64")
    for c in ("is_renting", "is_returning", "is_installed"):
        df[c] = df[c].astype("boolean")
    for c in ("system_id", "station_id"):
        df[c] = df[c].astype("string")
    df["fetched_at"] = pd.to_datetime(df["fetched_at"], utc=True)
    df["last_reported"] = pd.to_datetime(df["last_reported"], utc=True)
    return df


def parse_vehicle_status(
    doc: Mapping[str, Any], *, system_id: str, fetched_at: pd.Timestamp | None = None
) -> pd.DataFrame:
    """A ``free_bike_status`` / ``vehicle_status`` document, one row per vehicle.

    ``vehicle_id`` is read from ``vehicle_id`` or ``bike_id``; a record with neither is skipped.
    Flags that the feed omits stay missing (a vehicle that does not say it is disabled is not
    declared working).

    Examples
    --------
    >>> doc = {"data": {"bikes": [{"bike_id": "b1", "lat": 43.6, "lon": 3.87},
    ...                           {"vehicle_id": "b2", "is_disabled": True}]}}
    >>> out = parse_vehicle_status(doc, system_id="demo")
    >>> out["vehicle_id"].tolist(), out["is_disabled"].isna().tolist()
    (['b1', 'b2'], [True, False])
    """
    when = pd.Timestamp.now(tz="UTC") if fetched_at is None else to_utc([fetched_at]).iloc[0]
    rows = []
    for v in _records(doc.get("data", doc), "vehicles", "bikes"):
        vid = v.get("vehicle_id", v.get("bike_id"))
        if _missing(vid):
            continue
        rows.append(
            {
                "system_id": system_id,
                "vehicle_id": str(vid),
                "fetched_at": when,
                "station_id": _text(v.get("station_id")),
                "vehicle_type_id": _text(v.get("vehicle_type_id")),
                "lat": _float(v.get("lat")),
                "lon": _float(v.get("lon")),
                "is_disabled": _flag(v.get("is_disabled")),
                "is_reserved": _flag(v.get("is_reserved")),
            }
        )
    df = pd.DataFrame(rows, columns=_VEHICLE_COLUMNS)
    for c in ("is_disabled", "is_reserved"):
        df[c] = df[c].astype("boolean")
    for c in ("system_id", "vehicle_id", "station_id", "vehicle_type_id"):
        df[c] = df[c].astype("string")
    df["lat"] = df["lat"].astype("float64")
    df["lon"] = df["lon"].astype("float64")
    df["fetched_at"] = pd.to_datetime(df["fetched_at"], utc=True)
    return df


_PARSERS = {"station_status": parse_station_status, "vehicle_status": parse_vehicle_status}
_DTYPES: dict[str, dict[str, str]] = {
    "station_status": {
        "num_bikes_available": "Int64",
        "num_docks_available": "Int64",
        "is_renting": "boolean",
        "is_returning": "boolean",
        "is_installed": "boolean",
    },
    "vehicle_status": {"is_disabled": "boolean", "is_reserved": "boolean"},
}


@dataclass
class _State:
    url: str | None = None
    next_at: float = 0.0
    failures: int = 0
    reason: str = "skipped_ttl"
    etag: str | None = None
    last_modified: str | None = None
    unavailable: bool = False


@dataclass
class _Reply:
    data: dict[str, Any]
    etag: str | None = None
    last_modified: str | None = None


def _systems_mapping(systems: Mapping[str, str] | pd.DataFrame) -> dict[str, str]:
    if isinstance(systems, pd.DataFrame):
        url_col = next(
            (c for c in ("auto_discovery_url", "gbfs_url", "url") if c in systems.columns), None
        )
        if "system_id" not in systems.columns or url_col is None:
            raise ValueError(
                "a systems table needs a system_id column and one of auto_discovery_url, "
                "gbfs_url or url"
            )
        pairs = zip(systems["system_id"], systems[url_col], strict=True)
        return {str(s): str(u) for s, u in pairs if isinstance(u, str) and u}
    return {str(s): str(u) for s, u in systems.items()}


class Collector:
    """Poll the station and vehicle feeds of some systems and write what they publish.

    Parameters
    ----------
    systems : mapping or DataFrame
        ``{system_id: gbfs.json URL}``, or a frame with ``system_id`` and one of
        ``auto_discovery_url`` (as :func:`gbfs_toolkit.systems_catalog` returns), ``gbfs_url``
        or ``url``.
    out_dir : str or Path
        Where the day files go (created on demand).
    user_agent : str
        Required. Identify yourself, with a way to be reached.
    feeds : sequence of {"station_status", "vehicle_status"}, default ("station_status",)
        What to collect from each system.
    timeout : float, default 15
        Seconds before one request is abandoned.
    retries, backoff_factor : int, float
        HTTP-level retries of transient errors (429, 5xx), with exponential back-off.
    min_interval : float, default 1.0
        Never ask the same feed twice within this many seconds, whatever its ``ttl``.
    respect_ttl : bool, default True
        Wait for the feed's own ``ttl`` before asking again. ``False`` is for tests and for
        feeds whose ``ttl`` you know to be wrong; you then own the load you put on them.
    max_backoff : float, default 3600
        Longest wait after repeated failures, in seconds.
    max_workers : int, default 4
        Systems polled in parallel.
    get_json : callable, optional
        ``url -> dict``, replacing HTTP (no ``requests`` needed). The offline path.
    session, clock, now : optional
        A ``requests.Session``, a monotonic clock in seconds and a UTC clock, for tests.

    Raises
    ------
    ValueError
        If ``user_agent`` is empty, ``feeds`` holds an unknown kind or ``systems`` is empty.
    """

    def __init__(
        self,
        systems: Mapping[str, str] | pd.DataFrame,
        out_dir: str | Path,
        *,
        user_agent: str,
        feeds: Sequence[str] = ("station_status",),
        timeout: float = 15.0,
        retries: int = 2,
        backoff_factor: float = 0.5,
        min_interval: float = 1.0,
        respect_ttl: bool = True,
        max_backoff: float = 3600.0,
        max_workers: int = 4,
        get_json: Callable[[str], dict[str, Any]] | None = None,
        session: Any = None,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], pd.Timestamp] | None = None,
    ) -> None:
        if not isinstance(user_agent, str) or not user_agent.strip():
            raise ValueError(
                "user_agent is required: tell the operators who is polling them, "
                "e.g. 'my-lab-gbfs/1.0 (mailto:me@example.org)'"
            )
        bad = [f for f in feeds if f not in FEED_KINDS]
        if bad or not feeds:
            raise ValueError(f"feeds must be a non-empty subset of {FEED_KINDS}, got {list(feeds)}")
        self.systems = _systems_mapping(systems)
        if not self.systems:
            raise ValueError("no system to collect from")
        if not any(ch in user_agent for ch in ("@", "http")):
            _log.warning(
                "user_agent %r has no contact (e-mail or URL); operators prefer one", user_agent
            )
        self.out_dir = Path(out_dir)
        self.user_agent = user_agent.strip()
        self.feeds = tuple(dict.fromkeys(feeds))
        self.timeout = float(timeout)
        self.min_interval = float(min_interval)
        self.respect_ttl = respect_ttl
        self.max_backoff = float(max_backoff)
        self.max_workers = max(1, int(max_workers))
        self._get_json = get_json
        self._retries, self._backoff_factor = int(retries), float(backoff_factor)
        self._session = session
        self._clock = clock
        self._now = now or (lambda: pd.Timestamp.now(tz="UTC"))
        self._state: dict[tuple[str, str], _State] = {}
        self._locks: dict[Path, threading.Lock] = {}
        self._lock = threading.Lock()

    # -- transport ---------------------------------------------------------------------

    def _session_for_thread(self) -> Any:
        if self._session is None:
            from gbfs_toolkit.io.fetch import build_session

            self._session = build_session(total=self._retries, backoff_factor=self._backoff_factor)
        return self._session

    def _fetch(self, url: str, state: _State | None = None) -> _Reply:
        if self._get_json is not None:
            try:
                return _Reply(self._get_json(url))
            except GBFSError:
                raise
            except Exception as exc:  # noqa: BLE001 (any failure of a user-supplied getter)
                raise GBFSFetchError(f"failed to fetch {url}: {exc}") from exc
        from gbfs_toolkit.io.fetch import _require_requests

        requests = _require_requests()
        headers = {"User-Agent": self.user_agent, "Accept": "application/json"}
        if state is not None and state.etag:
            headers["If-None-Match"] = state.etag
        if state is not None and state.last_modified:
            headers["If-Modified-Since"] = state.last_modified
        try:
            resp = self._session_for_thread().get(url, timeout=self.timeout, headers=headers)
            if resp.status_code == 304:
                raise _NotModified
            resp.raise_for_status()
            payload = resp.json()
        except _NotModified:
            raise
        except (requests.RequestException, ValueError) as exc:
            raise GBFSFetchError(f"failed to fetch {url}: {exc}") from exc
        if not isinstance(payload, dict):
            raise GBFSFetchError(f"failed to fetch {url}: the document is not a JSON object")
        return _Reply(payload, resp.headers.get("ETag"), resp.headers.get("Last-Modified"))

    def _discover(self, system: str, kind: str) -> str | None:
        from gbfs_toolkit.io.fetch import parse_discovery

        feeds, _ = parse_discovery(self._fetch(self.systems[system]).data)
        for name in _FEED_NAMES[kind]:
            if name in feeds:
                return feeds[name]
        return None

    # -- one poll ----------------------------------------------------------------------

    def _poll_one(self, system: str, kind: str) -> dict[str, Any]:
        with self._lock:
            state = self._state.setdefault((system, kind), _State())
        row: dict[str, Any] = {"system_id": system, "feed": kind, "rows": 0, "error": None}
        now = self._clock()
        if state.next_at > now:
            return {**row, "outcome": state.reason}
        try:
            if state.url is None:
                state.url = self._discover(system, kind)
                if state.url is None:
                    state.next_at = now + _REDISCOVER_AFTER
                    state.reason = "unavailable"
                    _log.info("[%s] does not publish %s", system, kind)
                    return {**row, "outcome": "unavailable"}
            try:
                reply = self._fetch(state.url, state)
            except _NotModified:
                state.next_at = now + self.min_interval
                state.reason = "skipped_ttl"
                return {**row, "outcome": "skipped_ttl"}
            fetched_at = self._now()
            doc = reply.data
            frame = _PARSERS[kind](doc, system_id=system, fetched_at=fetched_at)
        except (GBFSError, ValueError, TypeError, AttributeError) as exc:
            state.failures += 1
            state.url = (
                state.url if state.failures < 5 else None
            )  # rediscover after repeated failures
            wait = min(self.max_backoff, max(self.min_interval, 1.0) * 2**state.failures)
            state.next_at = now + wait
            state.reason = "skipped_backoff"
            _log.warning(
                "[%s] %s failed (%d in a row), next try in %.0f s: %s",
                system,
                kind,
                state.failures,
                wait,
                exc,
            )
            return {**row, "outcome": "failed", "error": str(exc)}
        state.failures = 0
        state.etag, state.last_modified = reply.etag, reply.last_modified
        ttl = doc.get("ttl")
        ttl_s = float(ttl) if isinstance(ttl, (int, float)) and not isinstance(ttl, bool) else 0.0
        state.next_at = now + max(ttl_s if self.respect_ttl else 0.0, self.min_interval)
        state.reason = "skipped_ttl"
        if frame.empty:
            _log.info("[%s] %s listed nothing", system, kind)
            return {**row, "outcome": "empty"}
        self._append(kind, system, frame)
        return {**row, "outcome": "collected", "rows": int(len(frame))}

    def _append(self, kind: str, system: str, frame: pd.DataFrame) -> None:
        require_pyarrow("Collector")
        day = frame["fetched_at"].iloc[0].strftime("%Y-%m-%d")
        path = self.out_dir / kind / system / f"{day}.parquet"
        with self._lock:
            guard = self._locks.setdefault(path, threading.Lock())
        with guard:
            combined = frame
            if path.exists():
                old = pd.read_parquet(path).astype(_DTYPES[kind], errors="ignore")
                combined = pd.concat([old, frame], ignore_index=True)
            atomic_write(
                path, lambda tmp: combined.to_parquet(tmp, index=False, compression="zstd")
            )

    def poll_once(self) -> pd.DataFrame:
        """Poll every system and feed once (those still fresh or backing off are skipped).

        Returns
        -------
        pandas.DataFrame
            One row per (system, feed): ``system_id, feed, outcome`` (one of :data:`OUTCOMES`),
            ``rows`` written and ``error`` (text, for ``failed``). A failure never raises: it is
            logged and reported here, so one bad feed does not stop the others.
        """
        tasks = [(s, k) for s in self.systems for k in self.feeds]

        def work(task: tuple[str, str]) -> dict[str, Any]:
            try:
                return self._poll_one(*task)
            except Exception as exc:  # noqa: BLE001 (keep the other systems going)
                _log.exception("[%s] unexpected error on %s", *task)
                return {
                    "system_id": task[0],
                    "feed": task[1],
                    "outcome": "failed",
                    "rows": 0,
                    "error": f"{type(exc).__name__}: {exc}",
                }

        with ThreadPoolExecutor(max_workers=min(self.max_workers, len(tasks))) as pool:
            rows = list(pool.map(work, tasks))
        return pd.DataFrame(rows, columns=["system_id", "feed", "outcome", "rows", "error"])

    def poll_metadata(self, feeds: Sequence[str] = METADATA_FEEDS) -> pd.DataFrame:
        """Fetch the slowly changing feeds and keep a version only when their content changed.

        Each feed of each system is normalised (``to_canonical_*``), stamped with ``fetched_at``
        and handed to :func:`gbfs_toolkit.history.record_version`, which stores it under
        ``<out_dir>/metadata/<system_id>/<feed>/<UTC day>.parquet`` only if it differs from the
        latest version. Call it once a day; it does not wait for a ``ttl``.

        Returns
        -------
        pandas.DataFrame
            ``system_id, feed, outcome`` (``written``, ``unchanged``, ``unavailable``, ``failed``
            or a :class:`~gbfs_toolkit.history.VersionResult` action) and ``error``.
        """
        from gbfs_toolkit.history import record_version
        from gbfs_toolkit.io import normalize as nz
        from gbfs_toolkit.io.fetch import parse_discovery

        bad = [f for f in feeds if f not in METADATA_FEEDS]
        if bad:
            raise ValueError(
                f"unknown metadata feed(s) {bad}; expected a subset of {METADATA_FEEDS}"
            )

        def normalise(feed: str, doc: dict[str, Any], system: str) -> pd.DataFrame:
            if feed == "system_information":
                return pd.DataFrame([nz.to_canonical_system_information(doc, system_id=system)])
            if feed == "station_information":
                return nz.to_canonical_station_info(doc, system_id=system)
            if feed == "vehicle_types":
                return nz.to_canonical_vehicle_types(doc, system_id=system)
            if feed == "system_pricing_plans":
                return nz.to_canonical_pricing_plans(doc, system_id=system)
            return nz.to_canonical_system_regions(doc, system_id=system)

        rows: list[dict[str, Any]] = []
        for system, url in self.systems.items():
            try:
                urls, _ = parse_discovery(self._fetch(url).data)
            except GBFSError as exc:
                _log.warning("[%s] discovery failed: %s", system, exc)
                rows += [
                    {"system_id": system, "feed": f, "outcome": "failed", "error": str(exc)}
                    for f in feeds
                ]
                continue
            for feed in feeds:
                row = {"system_id": system, "feed": feed, "outcome": "unavailable", "error": None}
                rows.append(row)
                if feed not in urls:
                    continue
                try:
                    frame = normalise(feed, self._fetch(urls[feed]).data, system)
                    frame = frame.assign(fetched_at=self._now())
                    folder = self.out_dir / "metadata" / system / feed
                    row["outcome"] = record_version(frame, folder).action
                except (GBFSError, ValueError, TypeError, KeyError) as exc:
                    _log.warning("[%s] %s failed: %s", system, feed, exc)
                    row.update(outcome="failed", error=str(exc))
        return pd.DataFrame(rows, columns=["system_id", "feed", "outcome", "error"])

    def run(
        self,
        *,
        interval: float = 60.0,
        duration: float | None = None,
        max_iterations: int | None = None,
        sleep: Callable[[float], None] = time.sleep,
        on_poll: Callable[[int, pd.DataFrame], None] | None = None,
    ) -> dict[str, Any]:
        """Poll every ``interval`` seconds for ``duration`` seconds or ``max_iterations`` polls.

        With neither bound it runs until you interrupt it (Ctrl-C ends it cleanly). The loop
        lives in your process; nothing is left running when it returns.

        Returns
        -------
        dict
            ``iterations``, ``rows`` written and ``outcomes`` (a count per outcome).
        """
        if interval <= 0:
            raise ValueError("interval must be positive")
        started = self._clock()
        outcomes: Counter[str] = Counter()
        rows = 0
        iteration = 0
        try:
            while True:
                t0 = self._clock()
                iteration += 1
                result = self.poll_once()
                outcomes.update(result["outcome"])
                rows += int(result["rows"].sum())
                if on_poll is not None:
                    on_poll(iteration, result)
                if max_iterations is not None and iteration >= max_iterations:
                    break
                pause = max(0.0, interval - (self._clock() - t0))
                if duration is not None and self._clock() - started + pause >= duration:
                    break  # the next poll would fall after the end
                sleep(pause)
        except KeyboardInterrupt:
            _log.info("interrupted after %d iteration(s)", iteration)
        return {"iterations": iteration, "rows": rows, "outcomes": dict(outcomes)}


class _NotModified(Exception):  # noqa: N818 (internal control flow)
    """Internal: the server answered 304 to a conditional request."""


def read_collected(
    out_dir: str | Path,
    kind: str = "station_status",
    *,
    systems: Iterable[str] | None = None,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
    on_error: str = "skip",
) -> pd.DataFrame:
    """Read the day files a :class:`Collector` wrote, for some systems and days.

    ``start`` and ``end`` are UTC days (both inclusive, compared with the file names). An
    unreadable file (a truncated write, a copy cut short) is skipped with a warning
    (``on_error="skip"``) or raised (``on_error="raise"``). The result is sorted by time.

    Examples
    --------
    >>> import pandas as pd
    >>> read_collected("/nonexistent/folder").empty
    True
    """
    if kind not in FEED_KINDS:
        raise ValueError(f"kind must be one of {FEED_KINDS}, got {kind!r}")
    if on_error not in ("skip", "raise"):
        raise ValueError("on_error must be 'skip' or 'raise'")
    base = Path(out_dir) / kind
    lo = None if start is None else to_utc([start]).iloc[0].strftime("%Y-%m-%d")
    hi = None if end is None else to_utc([end]).iloc[0].strftime("%Y-%m-%d")
    wanted = None if systems is None else {str(s) for s in systems}
    frames = []
    if base.is_dir():
        require_pyarrow("read_collected")
        for folder in sorted(p for p in base.iterdir() if p.is_dir()):
            if wanted is not None and folder.name not in wanted:
                continue
            for f in sorted(folder.glob("????-??-??.parquet")):
                if (lo and f.stem < lo) or (hi and f.stem > hi):
                    continue
                try:
                    frames.append(pd.read_parquet(f).astype(_DTYPES[kind], errors="ignore"))
                except Exception as exc:  # noqa: BLE001 (pyarrow raises several types)
                    if on_error == "raise":
                        raise
                    _log.warning("skipping unreadable file %s: %s", f, exc)
    if not frames:
        return pd.DataFrame(
            columns=_STATION_COLUMNS if kind == "station_status" else _VEHICLE_COLUMNS
        )
    out = pd.concat(frames, ignore_index=True)
    sort = ["fetched_at", "system_id", "station_id" if kind == "station_status" else "vehicle_id"]
    return out.sort_values(sort).reset_index(drop=True)

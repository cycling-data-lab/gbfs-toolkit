"""Fetch / scrape live GBFS data with one line: discovery + a friendly feed object.

The goal is to make GBFS *trivial*: point at a ``gbfs.json`` (or a system id) and
get tidy, canonical DataFrames back, regardless of GBFS version or language.

    >>> import gbfs_toolkit as gb
    >>> df = gb.availability("https://.../gbfs.json")        # bikes/docks + name + coords
    >>> feed = gb.GBFSFeed.from_url("https://.../gbfs.json")
    >>> feed.version, feed.feeds.keys()
    >>> feed.station_status(); feed.vehicles(); feed.audit()

Networking uses ``requests`` (the optional ``[fetch]`` extra). For tests / offline
use, pass a ``get_json`` callable that maps a URL to an already-parsed dict.
"""

from __future__ import annotations

import logging
from collections import namedtuple
from collections.abc import Callable
from typing import Any

import pandas as pd

from gbfs_toolkit.audit import audit_frames
from gbfs_toolkit.core.errors import GBFSDiscoveryError, GBFSFetchError, GBFSNotModified
from gbfs_toolkit.io.normalize import (
    to_canonical_station_info,
    to_canonical_station_status,
    to_canonical_system_information,
    to_canonical_vehicle_types,
    to_canonical_vehicles,
)

_USER_AGENT = "gbfs-toolkit (+https://github.com/cycling-data-lab/gbfs-toolkit)"
_log = logging.getLogger("gbfs_toolkit")

JsonGetter = Callable[[str], dict]

#: Result of a conditional fetch: parsed ``data`` plus the caching headers to replay next time.
FeedResponse = namedtuple("FeedResponse", ["data", "etag", "last_modified"])

# Canonical feed names, with cross-version fallbacks.
_STATION_INFO = ("station_information",)
_STATION_STATUS = ("station_status",)
_VEHICLES = ("vehicle_status", "free_bike_status")  # v3, v2
_VEHICLE_TYPES = ("vehicle_types",)
_SYSTEM_INFO = ("system_information",)
_GEOFENCING = ("geofencing_zones",)
_SYSTEM_REGIONS = ("system_regions",)
_ALERTS = ("system_alerts",)


def _require_requests():
    try:
        import requests

        return requests
    except ImportError as e:  # pragma: no cover
        raise ImportError(
            "Fetching requires `requests`. Install with `pip install gbfs-toolkit[fetch]`, "
            "or pass a `get_json` callable for offline use."
        ) from e


def build_session(
    *,
    total: int = 3,
    backoff_factor: float = 0.5,
    status_forcelist: tuple[int, ...] = (429, 500, 502, 503, 504),
) -> Any:
    """A pooled ``requests.Session`` with polite retry/backoff: the right default for scraping.

    Transient 429/5xx responses from operator API gateways are routine; this retries them with
    exponential backoff instead of failing the whole poll. Reusing one session across systems
    also pools TCP connections (avoids port exhaustion). Requires the ``[fetch]`` extra.
    """
    requests = _require_requests()
    from requests.adapters import HTTPAdapter
    from urllib3.util import Retry

    session = requests.Session()
    retry = Retry(
        total=total,
        backoff_factor=backoff_factor,
        status_forcelist=list(status_forcelist),
        allowed_methods=frozenset({"GET", "HEAD"}),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update({"User-Agent": _USER_AGENT})
    return session


def _get_json(url: str, *, timeout: int = 30, session: Any = None) -> dict:
    """Fetch and parse a JSON document over HTTP (requires the ``[fetch]`` extra)."""
    requests = _require_requests()
    getter = session if session is not None else requests
    try:
        resp = getter.get(url, timeout=timeout, headers={"User-Agent": _USER_AGENT})
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        raise GBFSFetchError(f"failed to fetch {url}: {e}") from e


def _session_getter(session: Any, *, timeout: int = 30) -> JsonGetter:
    """A ``url -> dict`` getter bound to a ``requests.Session`` (connection reuse)."""

    def _get(url: str) -> dict:
        return _get_json(url, timeout=timeout, session=session)

    return _get


def fetch_feed_json(
    url: str,
    *,
    session: Any = None,
    etag: str | None = None,
    last_modified: str | None = None,
    timeout: int = 30,
) -> FeedResponse:
    """Conditionally fetch a feed, honouring HTTP caching: the polite way to poll.

    Pass the ``etag`` / ``last_modified`` returned by the previous call; if the server replies
    **304 Not Modified**, this raises :class:`~gbfs_toolkit.core.errors.GBFSNotModified` so your
    scraper can skip re-ingesting an unchanged snapshot (saving bandwidth and avoiding an
    IP ban). Otherwise returns a :data:`FeedResponse` ``(data, etag, last_modified)`` to store
    for next time. Requires the ``[fetch]`` extra.
    """
    requests = _require_requests()
    headers = {"User-Agent": _USER_AGENT}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    getter = session if session is not None else requests
    try:
        resp = getter.get(url, timeout=timeout, headers=headers)
    except requests.RequestException as e:
        raise GBFSFetchError(f"failed to fetch {url}: {e}") from e
    if resp.status_code == 304:
        raise GBFSNotModified(url)
    resp.raise_for_status()
    return FeedResponse(resp.json(), resp.headers.get("ETag"), resp.headers.get("Last-Modified"))


def _utc_ts(value: Any) -> pd.Timestamp:
    """Parse a GBFS top-level ``last_updated`` (unix or RFC3339) to a UTC Timestamp."""
    if value is None:
        return pd.NaT
    if isinstance(value, (int, float)):
        return pd.to_datetime(value, unit="s", utc=True)
    try:
        return pd.to_datetime(float(value), unit="s", utc=True)
    except (TypeError, ValueError):
        return pd.to_datetime(value, errors="coerce", utc=True)


def parse_discovery(doc: dict, language: str | None = None) -> tuple[dict[str, str], str]:
    """Parse a ``gbfs.json`` auto-discovery document → ({feed_name: url}, version).

    Handles GBFS 2.x (``data`` keyed by language) and 3.x (``data.feeds`` directly).
    """
    version = str(doc.get("version", "2.x"))
    data = doc.get("data", {})
    if isinstance(data, dict) and "feeds" in data:  # GBFS 3.x
        feeds = data["feeds"]
    elif isinstance(data, dict) and data:  # GBFS 1.x / 2.x, keyed by language
        key = language if (language and language in data) else next(iter(data))
        feeds = data.get(key, {}).get("feeds", [])
    else:
        feeds = []
    mapping = {f.get("name"): f.get("url") for f in feeds if f.get("name") and f.get("url")}
    return mapping, version


class GBFSFeed:
    """A friendly handle on one GBFS system: discover once, fetch tidy frames.

    Parameters
    ----------
    gbfs_url : str
        URL of the system's ``gbfs.json`` auto-discovery file.
    language : str, optional
        Preferred language key for multi-language (GBFS 2.x) feeds.
    system_id : str, optional
        Stamped on every returned frame (defaults to ``"system"``).
    timeout : int, default 30
    get_json : callable, optional
        ``url -> dict`` override (dependency injection for tests / caching).
    """

    def __init__(
        self,
        gbfs_url: str | None = None,
        *,
        language: str | None = None,
        system_id: str = "system",
        timeout: int = 30,
        get_json: JsonGetter | None = None,
    ) -> None:
        self.gbfs_url = gbfs_url
        self.system_id = system_id
        self.timeout = timeout
        self._language = language
        self._get_json: JsonGetter = get_json or (lambda url: _get_json(url, timeout=timeout))
        self._feeds: dict[str, str] | None = None
        self._version: str | None = None
        self._doc: dict | None = None
        self._sysinfo: dict | None = None
        self._raw_cache: dict[str, Any] = {}

    # -- display (cached state only; never triggers a network call) ---------
    def __repr__(self) -> str:
        ver = self._version or "?"
        n = len(self._feeds) if self._feeds is not None else "?"
        return f"GBFSFeed(system_id={self.system_id!r}, version={ver!r}, feeds={n})"

    def _repr_html_(self) -> str:
        if self._feeds is None:
            feeds = "<em>not discovered yet</em>"
        else:
            feeds = ", ".join(f"<code>{f}</code>" for f in sorted(self._feeds)) or "none"
        return (
            f"<b>GBFSFeed</b> <code>{self.system_id}</code>"
            f"<br>version: {self._version or '?'}<br>feeds: {feeds}"
        )

    # -- constructors -------------------------------------------------------
    @classmethod
    def from_url(cls, gbfs_url: str, **kwargs: Any) -> GBFSFeed:
        """Build a feed from its ``gbfs.json`` URL."""
        return cls(gbfs_url, **kwargs)

    @classmethod
    def from_system_id(
        cls, system_id: str, *, catalog: pd.DataFrame | None = None, **kwargs: Any
    ) -> GBFSFeed:
        """Build a feed by resolving ``system_id`` through the MobilityData catalogue."""
        from gbfs_toolkit.io.catalog import resolve, systems_catalog

        cat = catalog if catalog is not None else systems_catalog()
        info = resolve(system_id, cat)
        return cls(info["auto_discovery_url"], system_id=info["system_id"], **kwargs)

    # -- getters / setters --------------------------------------------------
    @property
    def language(self) -> str | None:
        """Preferred feed language (GBFS 2.x). Setting it re-discovers the feeds."""
        return self._language

    @language.setter
    def language(self, value: str | None) -> None:
        if value != self._language:
            self._language = value
            self._feeds = self._version = self._doc = None
            self._raw_cache.clear()

    @property
    def feeds(self) -> dict[str, str]:
        """Mapping ``{feed_name: url}`` discovered from ``gbfs.json`` (cached)."""
        if self._feeds is None:
            self._discover()
        return dict(self._feeds or {})

    @property
    def version(self) -> str:
        """The GBFS spec version advertised by the feed (cached)."""
        if self._version is None:
            self._discover()
        return self._version or "2.x"

    @property
    def ttl(self) -> int | None:
        """Advertised refresh interval (seconds) from ``gbfs.json``; feeds the staleness audit."""
        if self._doc is None:
            self._discover()
        ttl = (self._doc or {}).get("ttl")
        return int(ttl) if ttl is not None else None

    @property
    def last_updated(self) -> pd.Timestamp:
        """When the discovery document was last updated (tz-aware UTC), or NaT."""
        if self._doc is None:
            self._discover()
        return _utc_ts((self._doc or {}).get("last_updated"))

    @property
    def timezone(self) -> str | None:
        """IANA timezone (e.g. ``"Europe/Paris"``) from ``system_information``, for local time."""
        return self.system_information().get("timezone")

    def has(self, *names: str) -> bool:
        """True if any of ``names`` is an available feed."""
        return any(n in self.feeds for n in names)

    # -- internals ----------------------------------------------------------
    def _discover(self) -> None:
        if self.gbfs_url is None:
            raise GBFSDiscoveryError(
                "no gbfs_url set; use GBFSFeed.from_url(...) or from_system_id(...)"
            )
        self._doc = self._get_json(self.gbfs_url)
        self._feeds, self._version = parse_discovery(self._doc, self._language)

    def _raw(self, names: tuple[str, ...]) -> dict:
        feeds = self.feeds
        name = next((n for n in names if n in feeds), None)
        if name is None:
            raise GBFSDiscoveryError(f"none of {names} present; available: {sorted(feeds)}")
        if name not in self._raw_cache:
            self._raw_cache[name] = self._get_json(feeds[name])
        return self._raw_cache[name]

    # -- tidy data ----------------------------------------------------------
    def station_information(self) -> pd.DataFrame:
        """Canonical static station inventory."""
        return to_canonical_station_info(
            self._raw(_STATION_INFO), system_id=self.system_id, gbfs_version=self.version
        )

    def station_status(self) -> pd.DataFrame:
        """Canonical timestamped availability snapshot."""
        return to_canonical_station_status(
            self._raw(_STATION_STATUS), system_id=self.system_id, gbfs_version=self.version
        )

    def vehicles(self) -> pd.DataFrame:
        """Canonical free-floating vehicle positions (``vehicle_status``/``free_bike_status``)."""
        return to_canonical_vehicles(
            self._raw(_VEHICLES), system_id=self.system_id, gbfs_version=self.version
        )

    def vehicle_types(self) -> pd.DataFrame:
        """Canonical ``vehicle_types`` catalogue (form factor / propulsion / range)."""
        return to_canonical_vehicle_types(self._raw(_VEHICLE_TYPES), system_id=self.system_id)

    def geofencing_zones(self) -> Any:
        """Operator-defined service-area polygons as a ``GeoDataFrame`` (``[geo]`` extra).

        Raises ``KeyError`` if the system publishes no ``geofencing_zones`` feed; check
        :meth:`has` first. See :func:`~gbfs_toolkit.to_canonical_geofencing`.
        """
        from gbfs_toolkit.spatial.geofencing import to_canonical_geofencing

        return to_canonical_geofencing(
            self._raw(_GEOFENCING), system_id=self.system_id, gbfs_version=self.version
        )

    def system_regions(self) -> pd.DataFrame:
        """Canonical ``region_id → name`` lookup (raises if the feed has no ``system_regions``)."""
        from gbfs_toolkit.io.normalize import to_canonical_system_regions

        return to_canonical_system_regions(self._raw(_SYSTEM_REGIONS), system_id=self.system_id)

    def alerts(self) -> pd.DataFrame:
        """Canonical service alerts (raises if the feed has no ``system_alerts``)."""
        from gbfs_toolkit.io.normalize import to_canonical_alerts

        return to_canonical_alerts(self._raw(_ALERTS), system_id=self.system_id)

    def system_information(self) -> dict:
        """System metadata (name, **timezone**, language, operator), cached."""
        if self._sysinfo is None:
            self._sysinfo = to_canonical_system_information(
                self._raw(_SYSTEM_INFO), system_id=self.system_id
            )
        return dict(self._sysinfo)

    def availability(self) -> pd.DataFrame:
        """**The daily one-liner**: live status joined with station info.

        Thin convenience over :func:`~gbfs_toolkit.join_availability`; returns bikes/docks
        *and* name, coordinates, capacity and station type in one tidy frame (outer join with a
        ``presence`` indicator). For offline frames (e.g. from a Parquet lake), call
        ``join_availability(info, status)`` directly.
        """
        from gbfs_toolkit.analytics.frames import join_availability

        return join_availability(self.station_information(), self.station_status())

    def to_local_time(
        self, df: pd.DataFrame, columns: tuple[str, ...] = ("fetched_at",)
    ) -> pd.DataFrame:
        """Convert UTC timestamp columns to the system's local timezone (diurnal analysis)."""
        tz = self.timezone
        if not tz:
            return df
        out = df.copy()
        for col in columns:
            if col in out:
                out[col] = pd.to_datetime(out[col], utc=True).dt.tz_convert(tz)
        return out

    def audit(self) -> pd.DataFrame:
        """Unified semantic audit: **static** (A1–A7) on the inventory **and** **dynamic**
        (D1–D3) on live availability, stacked with an ``audit_type`` column.

        Thin convenience over :func:`~gbfs_toolkit.audit_frames` (dynamic staleness uses the
        feed's advertised ``ttl``). For offline frames, call ``audit_frames(info, status)``.
        """
        status = self.station_status() if self.has(*_STATION_STATUS) else None
        return audit_frames(
            self.station_information(),
            status,
            ttl_seconds=self.ttl if status is not None else None,
            system_id=self.system_id,
        )

    def reconcile_fleet(self) -> pd.Series:
        """One authoritative fleet tally across the docked and free-floating feeds.

        Pulls ``station_status`` and/or ``vehicle_status`` (whichever exist) and reconciles
        them, excluding vehicles parked at stations from the deployed total so the two feeds
        don't double-count. See :func:`~gbfs_toolkit.reconcile_fleet_state`.
        """
        from gbfs_toolkit.analytics.fleet import reconcile_fleet_state

        status = self.station_status() if self.has(*_STATION_STATUS) else None
        vehicles = self.vehicles() if self.has(*_VEHICLES) else None
        return reconcile_fleet_state(status, vehicles)

    def snapshot(self) -> dict[str, pd.DataFrame]:
        """All available tidy frames at once: ``information``, ``status`` (+ ``vehicles``)."""
        out = {"information": self.station_information(), "status": self.station_status()}
        if self.has(*_VEHICLES):
            out["vehicles"] = self.vehicles()
        return out

    def summary(self) -> pd.Series:
        """A one-glance health card: counts, staleness, version; ideal in a notebook."""
        data: dict[str, Any] = {
            "system_id": self.system_id,
            "gbfs_version": self.version,
            "feeds": ", ".join(sorted(self.feeds)),
        }
        if self.has(*_STATION_INFO):
            data["total_stations"] = int(len(self.station_information()))
        if self.has(*_STATION_STATUS):
            status = self.station_status()
            data["total_bikes_available"] = int(
                pd.to_numeric(status["num_bikes_available"], errors="coerce").fillna(0).sum()
            )
            lag = status["fetched_at"] - status["last_reported"]
            data["feed_staleness_min"] = round(float(lag.dt.total_seconds().median() / 60), 1)
        if self.has(*_VEHICLES):
            data["total_vehicles"] = int(len(self.vehicles()))
        return pd.Series(data)


# -- top-level convenience (the "simplify GBFS to one line" surface) --------


def availability(gbfs_url: str, **kwargs: Any) -> pd.DataFrame:
    """One-liner: live availability (bikes/docks + name/coords) from a ``gbfs.json`` URL."""
    return GBFSFeed.from_url(gbfs_url, **kwargs).availability()


def audit_feed(gbfs_url: str, **kwargs: Any) -> pd.DataFrame:
    """One-liner: A1–A7 semantic audit of a live feed."""
    return GBFSFeed.from_url(gbfs_url, **kwargs).audit()


def _with_progress(iterable: Any, total: int, desc: str) -> Any:
    """Wrap ``iterable`` with a tqdm bar when tqdm is installed, else log every ~10%.

    Graceful degradation: an interactive pull shows a live bar with ``[cli]`` installed;
    a headless run (cron, pipeline) still reports progress through the ``gbfs_toolkit``
    logger without pulling in a UI dependency.
    """
    try:
        from tqdm import tqdm

        return tqdm(iterable, total=total, desc=desc, unit="feed")
    except ImportError:

        def _logged() -> Any:
            step = max(1, total // 10)
            for i, item in enumerate(iterable, 1):
                if i == total or i % step == 0:
                    _log.info("%s: %d/%d", desc, i, total)
                yield item

        return _logged()


def fetch_multiple(
    system_ids: list[str],
    *,
    catalog: pd.DataFrame | None = None,
    max_workers: int = 5,
    session: Any = None,
    progress: bool = False,
    **kwargs: Any,
) -> dict[str, GBFSFeed | Exception]:
    """Resolve and open many systems concurrently (threaded) for comparative studies.

    Returns ``{system_id: GBFSFeed}``, or the ``Exception`` for systems that failed,
    so one dead feed never sinks a 50-city pull. Discovery runs eagerly so failures
    surface here; data fetches stay lazy on each returned feed.

    Pass a shared ``requests.Session`` to pool connections across all systems (strongly
    recommended for repeated polling, avoids TCP/port exhaustion). Ignored if you also
    pass your own ``get_json``.

    Set ``progress=True`` for feedback on a long pull: a tqdm bar when tqdm is installed
    (``pip install gbfs-toolkit[cli]``), otherwise periodic log lines. Feeds complete out
    of order; a failure is logged and recorded, never raised, so the bar always finishes.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from gbfs_toolkit.io.catalog import systems_catalog

    cat = catalog if catalog is not None else systems_catalog()
    if "get_json" not in kwargs:
        # Default to a pooled, retry/backoff session so one flaky feed never sinks the batch.
        session = session if session is not None else build_session()
        kwargs = {**kwargs, "get_json": _session_getter(session, timeout=kwargs.get("timeout", 30))}

    def _open(sid: str) -> GBFSFeed:
        feed = GBFSFeed.from_system_id(sid, catalog=cat, **kwargs)
        _ = feed.feeds  # force discovery so a broken gbfs.json fails now
        return feed

    results: dict[str, GBFSFeed | Exception] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_open, sid): sid for sid in system_ids}
        done = as_completed(futures)
        if progress:
            done = _with_progress(done, total=len(futures), desc="fetching feeds")
        for fut in done:
            sid = futures[fut]
            try:
                results[sid] = fut.result()
            except Exception as exc:  # noqa: BLE001 (we deliberately capture per-system)
                results[sid] = exc
                _log.warning("fetch_multiple: %s failed (%s)", sid, exc)
    return results

"""Fetch / scrape live GBFS data with one line — discovery + a friendly feed object.

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

from collections.abc import Callable
from typing import Any

import pandas as pd

from gbfs_toolkit.audit import audit_dynamic, audit_static
from gbfs_toolkit.normalize import (
    to_canonical_station_info,
    to_canonical_station_status,
    to_canonical_system_information,
    to_canonical_vehicle_types,
    to_canonical_vehicles,
)

_USER_AGENT = "gbfs-toolkit (+https://github.com/cycling-data-lab/gbfs-toolkit)"

JsonGetter = Callable[[str], dict]

# Canonical feed names, with cross-version fallbacks.
_STATION_INFO = ("station_information",)
_STATION_STATUS = ("station_status",)
_VEHICLES = ("vehicle_status", "free_bike_status")  # v3, v2
_VEHICLE_TYPES = ("vehicle_types",)
_SYSTEM_INFO = ("system_information",)
_GEOFENCING = ("geofencing_zones",)
_AUDIT_COLS = ["system_id", "station_id", "audit_type", "flagged", "reason"]


def _get_json(url: str, *, timeout: int = 30) -> dict:
    """Fetch and parse a JSON document over HTTP (requires the ``[fetch]`` extra)."""
    try:
        import requests
    except ImportError as e:  # pragma: no cover
        raise ImportError(
            "Fetching requires `requests`. Install with `pip install gbfs-toolkit[fetch]`, "
            "or pass a `get_json` callable for offline use."
        ) from e
    resp = requests.get(url, timeout=timeout, headers={"User-Agent": _USER_AGENT})
    resp.raise_for_status()
    return resp.json()


def _session_getter(session: Any, *, timeout: int = 30) -> JsonGetter:
    """A ``url -> dict`` getter bound to a ``requests.Session`` (connection reuse).

    Sharing one pooled session across many systems avoids opening/closing a TCP
    connection per request — essential when polling dozens of feeds on a schedule.
    """

    def _get(url: str) -> dict:
        resp = session.get(url, timeout=timeout, headers={"User-Agent": _USER_AGENT})
        resp.raise_for_status()
        return resp.json()

    return _get


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
    elif isinstance(data, dict) and data:  # GBFS 1.x / 2.x — keyed by language
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
        from gbfs_toolkit.catalog import resolve, systems_catalog

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
        """Advertised refresh interval (seconds) from ``gbfs.json`` — feeds the staleness audit."""
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
        """IANA timezone (e.g. ``"Europe/Paris"``) from ``system_information`` — for local time."""
        return self.system_information().get("timezone")

    def has(self, *names: str) -> bool:
        """True if any of ``names`` is an available feed."""
        return any(n in self.feeds for n in names)

    # -- internals ----------------------------------------------------------
    def _discover(self) -> None:
        if self.gbfs_url is None:
            raise ValueError("no gbfs_url set; use GBFSFeed.from_url(...) or from_system_id(...)")
        self._doc = self._get_json(self.gbfs_url)
        self._feeds, self._version = parse_discovery(self._doc, self._language)

    def _raw(self, names: tuple[str, ...]) -> dict:
        feeds = self.feeds
        name = next((n for n in names if n in feeds), None)
        if name is None:
            raise KeyError(f"none of {names} present; available: {sorted(feeds)}")
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

        Raises ``KeyError`` if the system publishes no ``geofencing_zones`` feed — check
        :meth:`has` first. See :func:`~gbfs_toolkit.to_canonical_geofencing`.
        """
        from gbfs_toolkit.geofencing import to_canonical_geofencing

        return to_canonical_geofencing(
            self._raw(_GEOFENCING), system_id=self.system_id, gbfs_version=self.version
        )

    def system_information(self) -> dict:
        """System metadata (name, **timezone**, language, operator), cached."""
        if self._sysinfo is None:
            self._sysinfo = to_canonical_system_information(
                self._raw(_SYSTEM_INFO), system_id=self.system_id
            )
        return dict(self._sysinfo)

    def availability(self) -> pd.DataFrame:
        """**The daily one-liner**: live status joined with station info.

        Returns bikes/docks *and* name, coordinates, capacity and station type in a
        single tidy frame. Uses an **outer** join (operators routinely add/drop a
        station from one endpoint mid-sync), with a ``presence`` indicator
        (``both`` / ``status_only`` / ``info_only``) so orphaned rows are visible,
        not silently dropped.
        """
        info = self.station_information()
        status = self.station_status()
        merged = status.merge(
            info.drop(columns=["system_id"]),
            on="station_id",
            how="outer",
            suffixes=("", "_info"),
            indicator="presence",
        )
        merged["presence"] = (
            merged["presence"]
            .cat.rename_categories(
                {"both": "both", "left_only": "status_only", "right_only": "info_only"}
            )
            .astype("string")
        )
        return merged

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

        Dynamic staleness uses the feed's advertised ``ttl``. Use
        :func:`~gbfs_toolkit.audit.audit_static` / :func:`~gbfs_toolkit.audit.audit_dynamic`
        directly if you need the per-rule boolean columns.
        """
        static = audit_static(self.station_information()).assign(audit_type="static")
        parts = [static[_AUDIT_COLS]]
        if self.has(*_STATION_STATUS):
            dyn = audit_dynamic(self.availability(), ttl_seconds=self.ttl).assign(
                audit_type="dynamic", system_id=self.system_id
            )
            parts.append(dyn[_AUDIT_COLS])
        return pd.concat(parts, ignore_index=True)

    def snapshot(self) -> dict[str, pd.DataFrame]:
        """All available tidy frames at once: ``information``, ``status`` (+ ``vehicles``)."""
        out = {"information": self.station_information(), "status": self.station_status()}
        if self.has(*_VEHICLES):
            out["vehicles"] = self.vehicles()
        return out

    def summary(self) -> pd.Series:
        """A one-glance health card: counts, staleness, version — ideal in a notebook."""
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


def fetch_multiple(
    system_ids: list[str],
    *,
    catalog: pd.DataFrame | None = None,
    max_workers: int = 5,
    session: Any = None,
    **kwargs: Any,
) -> dict[str, GBFSFeed | Exception]:
    """Resolve and open many systems concurrently (threaded) for comparative studies.

    Returns ``{system_id: GBFSFeed}``, or the ``Exception`` for systems that failed —
    so one dead feed never sinks a 50-city pull. Discovery runs eagerly so failures
    surface here; data fetches stay lazy on each returned feed.

    Pass a shared ``requests.Session`` to pool connections across all systems (strongly
    recommended for repeated polling — avoids TCP/port exhaustion). Ignored if you also
    pass your own ``get_json``.
    """
    from concurrent.futures import ThreadPoolExecutor

    from gbfs_toolkit.catalog import systems_catalog

    cat = catalog if catalog is not None else systems_catalog()
    if session is not None and "get_json" not in kwargs:
        kwargs = {**kwargs, "get_json": _session_getter(session, timeout=kwargs.get("timeout", 30))}

    def _open(sid: str) -> GBFSFeed:
        feed = GBFSFeed.from_system_id(sid, catalog=cat, **kwargs)
        _ = feed.feeds  # force discovery so a broken gbfs.json fails now
        return feed

    results: dict[str, GBFSFeed | Exception] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_open, sid): sid for sid in system_ids}
        for fut in futures:
            sid = futures[fut]
            try:
                results[sid] = fut.result()
            except Exception as exc:  # noqa: BLE001 — we deliberately capture per-system
                results[sid] = exc
    return results

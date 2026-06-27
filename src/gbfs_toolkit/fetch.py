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

from gbfs_toolkit.audit import audit_static
from gbfs_toolkit.normalize import (
    to_canonical_station_info,
    to_canonical_station_status,
    to_canonical_vehicles,
)

_USER_AGENT = "gbfs-toolkit (+https://github.com/cycling-data-lab/gbfs-toolkit)"

JsonGetter = Callable[[str], dict]

# Canonical feed names, with cross-version fallbacks.
_STATION_INFO = ("station_information",)
_STATION_STATUS = ("station_status",)
_VEHICLES = ("vehicle_status", "free_bike_status")  # v3, v2


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
            self._feeds = self._version = None
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

    def has(self, *names: str) -> bool:
        """True if any of ``names`` is an available feed."""
        return any(n in self.feeds for n in names)

    # -- internals ----------------------------------------------------------
    def _discover(self) -> None:
        if self.gbfs_url is None:
            raise ValueError("no gbfs_url set; use GBFSFeed.from_url(...) or from_system_id(...)")
        doc = self._get_json(self.gbfs_url)
        self._feeds, self._version = parse_discovery(doc, self._language)

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

    def availability(self) -> pd.DataFrame:
        """**The daily one-liner**: live status joined with station info.

        Returns bikes/docks *and* name, coordinates, capacity and station type in a
        single tidy frame — what you almost always actually want.
        """
        info = self.station_information()
        status = self.station_status()
        return status.merge(
            info.drop(columns=["system_id"]), on="station_id", how="left", suffixes=("", "_info")
        )

    def audit(self) -> pd.DataFrame:
        """Run the A1–A7 semantic audit on this feed's station inventory."""
        return audit_static(self.station_information())

    def snapshot(self) -> dict[str, pd.DataFrame]:
        """All available tidy frames at once: ``information``, ``status`` (+ ``vehicles``)."""
        out = {"information": self.station_information(), "status": self.station_status()}
        if self.has(*_VEHICLES):
            out["vehicles"] = self.vehicles()
        return out


# -- top-level convenience (the "simplify GBFS to one line" surface) --------


def availability(gbfs_url: str, **kwargs: Any) -> pd.DataFrame:
    """One-liner: live availability (bikes/docks + name/coords) from a ``gbfs.json`` URL."""
    return GBFSFeed.from_url(gbfs_url, **kwargs).availability()


def audit_feed(gbfs_url: str, **kwargs: Any) -> pd.DataFrame:
    """One-liner: A1–A7 semantic audit of a live feed."""
    return GBFSFeed.from_url(gbfs_url, **kwargs).audit()

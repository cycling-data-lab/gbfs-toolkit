"""Feed discovery — the global MobilityData systems catalogue and per-feed resolution.

The community registry of GBFS systems is MobilityData's ``systems.csv``. This
module loads it (from a URL or a local copy) into a tidy frame and resolves a
system's ``auto_discovery_url`` (the ``gbfs.json`` entry point).
"""

from __future__ import annotations

import io
import logging
import re
import warnings
from pathlib import Path

import pandas as pd

from gbfs_toolkit.errors import GBFSFetchError

#: MobilityData's canonical registry of GBFS systems.
DEFAULT_CATALOG_URL = "https://raw.githubusercontent.com/MobilityData/gbfs/master/systems.csv"

#: Regex → canonical operator brand, applied to a lowercased system id / name.
#: Order matters (first match wins). Non-lossy: an unmatched value is returned unchanged.
OPERATOR_PATTERNS: list[tuple[str, str]] = [
    (r"v[eé]lib|smovengo", "Vélib' Métropole"),
    (r"jcdecaux|cyclocity", "JCDecaux"),
    (r"\blime\b", "Lime"),
    (r"\bdott\b", "Dott"),
    (r"\btier\b", "TIER"),
    (r"\bvoi\b", "Voi"),
    (r"\bbird\b", "Bird"),
    (r"\bpony\b", "Pony"),
    (r"nextbike", "Nextbike"),
    (r"donkey", "Donkey Republic"),
    (r"citi\s?bike|\blyft\b|motivate", "Lyft / Motivate"),
    (r"\bbixi\b", "BIXI"),
    (r"divvy", "Divvy"),
    (r"capital bikeshare|\bcabi\b", "Capital Bikeshare"),
    (r"\bmobi\b", "Mobi"),
    (r"ecobici", "Ecobici"),
    (r"call a bike|callabike", "Call a Bike"),
    (r"\bbcycle\b", "BCycle"),
    (r"veturilo", "Veturilo"),
    (r"\bspin\b", "Spin"),
]


def normalize_operator(value: str | None, *, default: str | None = None) -> str | None:
    """Canonicalise an operator brand from a system id / name (``"smovengo"`` → ``"Vélib'
    Métropole"``).

    Pattern-matches against :data:`OPERATOR_PATTERNS` (case-insensitive). On no match returns
    ``default`` if given, else the original value unchanged (non-lossy) — safe to apply across a
    whole catalogue so only recognised brands get collapsed.
    """
    if value is None:
        return default
    s = str(value).lower()
    for pattern, brand in OPERATOR_PATTERNS:
        if re.search(pattern, s):
            return brand
    return default if default is not None else str(value)


#: Local cache of the last successfully-downloaded catalogue (offline fallback).
CACHE_PATH = Path.home() / ".cache" / "gbfs-toolkit" / "systems.csv"
_log = logging.getLogger("gbfs_toolkit")
_MEMO: dict[str, pd.DataFrame] = {}  # in-process parsed-catalogue cache (speed)


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    return df


def systems_catalog(
    source: str | None = None,
    *,
    timeout: int = 30,
    use_cache: bool = True,
    refresh: bool = False,
) -> pd.DataFrame:
    """Load the MobilityData systems catalogue, cached in-process and on disk.

    The parsed catalogue is memoised for the life of the process, so resolving many systems in
    a loop hits the network once. On a successful download it is also cached to
    :data:`CACHE_PATH`; if a later download fails (network down, registry outage) the disk copy
    is used with a warning, so a long-running study never breaks on a transient outage. A fresh
    copy is returned each call (safe to mutate).

    Parameters
    ----------
    source : str, optional
        URL or local path to a ``systems.csv``. Defaults to :data:`DEFAULT_CATALOG_URL`
        (requires the optional ``[fetch]`` extra).
    timeout : int, default 30
        HTTP timeout in seconds (only when fetching a URL).
    use_cache : bool, default True
        Use the in-process / disk caches.
    refresh : bool, default False
        Force a re-download, ignoring (and replacing) the in-process cache.

    Returns
    -------
    pandas.DataFrame
        The catalogue with normalised lowercase column names.
    """
    key = source or DEFAULT_CATALOG_URL
    if use_cache and not refresh and key in _MEMO:
        return _MEMO[key].copy()
    df = _load_catalog(key, timeout=timeout, disk_cache=use_cache)
    if use_cache:
        _MEMO[key] = df
    return df.copy()


def _load_catalog(source: str, *, timeout: int, disk_cache: bool) -> pd.DataFrame:
    if not source.startswith(("http://", "https://")):
        return _normalize_columns(pd.read_csv(source))

    import requests

    try:
        resp = requests.get(source, timeout=timeout, headers={"User-Agent": "gbfs-toolkit"})
        resp.raise_for_status()
        df = _normalize_columns(pd.read_csv(io.StringIO(resp.text)))
        if disk_cache:
            try:
                CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
                CACHE_PATH.write_text(resp.text, encoding="utf-8")
            except OSError:  # pragma: no cover - caching is best-effort
                _log.debug("could not write catalogue cache to %s", CACHE_PATH)
        return df
    except (requests.RequestException, pd.errors.ParserError) as e:
        if disk_cache and CACHE_PATH.exists():
            warnings.warn(
                f"systems catalogue download failed ({e}); using cached copy at {CACHE_PATH}.",
                stacklevel=2,
            )
            return _normalize_columns(pd.read_csv(CACHE_PATH))
        raise GBFSFetchError(f"failed to load systems catalogue from {source}: {e}") from e


def filter_catalog(
    catalog: pd.DataFrame,
    *,
    country_code: str | None = None,
    city: str | None = None,
    name: str | None = None,
) -> pd.DataFrame:
    """Filter the systems catalogue — because you know "Paris", not the system_id.

    All filters are case-insensitive; ``city`` / ``name`` match as substrings against
    the catalogue's ``location`` / ``name`` columns (whichever are present).
    """
    out = catalog
    if country_code is not None and "country_code" in out.columns:
        out = out[out["country_code"].astype(str).str.lower() == country_code.lower()]
    if city is not None:
        col = next((c for c in ("location", "city", "name") if c in out.columns), None)
        if col:
            out = out[out[col].astype(str).str.contains(city, case=False, na=False)]
    if name is not None and "name" in out.columns:
        out = out[out["name"].astype(str).str.contains(name, case=False, na=False)]
    return out.reset_index(drop=True)


def resolve(system_id: str, catalog: pd.DataFrame) -> dict:
    """Resolve a system's discovery endpoint from a loaded catalogue.

    Returns a dict with at least ``system_id``, ``name``, ``country_code`` and
    ``auto_discovery_url`` (the ``gbfs.json``). Raises ``KeyError`` if not found.
    """
    id_col = "system_id" if "system_id" in catalog.columns else catalog.columns[0]
    url_col = next(
        (c for c in catalog.columns if ("auto" in c and "discovery" in c) or c == "url"),
        None,
    )
    hit = catalog[catalog[id_col].astype(str).str.lower() == str(system_id).lower()]
    if hit.empty:
        raise KeyError(f"system_id {system_id!r} not found in catalogue")
    row = hit.iloc[0]
    return {
        "system_id": str(row[id_col]),
        "name": row.get("name"),
        "country_code": row.get("country_code"),
        "auto_discovery_url": row.get(url_col) if url_col else None,
    }

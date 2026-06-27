"""Feed discovery — the global MobilityData systems catalogue and per-feed resolution.

The community registry of GBFS systems is MobilityData's ``systems.csv``. This
module loads it (from a URL or a local copy) into a tidy frame and resolves a
system's ``auto_discovery_url`` (the ``gbfs.json`` entry point).
"""

from __future__ import annotations

import io
import logging
import warnings
from pathlib import Path

import pandas as pd

from gbfs_toolkit.errors import GBFSFetchError

#: MobilityData's canonical registry of GBFS systems.
DEFAULT_CATALOG_URL = "https://raw.githubusercontent.com/MobilityData/gbfs/master/systems.csv"
#: Local cache of the last successfully-downloaded catalogue (offline fallback).
CACHE_PATH = Path.home() / ".cache" / "gbfs-toolkit" / "systems.csv"
_log = logging.getLogger("gbfs_toolkit")


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    return df


def systems_catalog(
    source: str | None = None, *, timeout: int = 30, use_cache: bool = True
) -> pd.DataFrame:
    """Load the MobilityData systems catalogue, with an offline cache fallback.

    On a successful download the catalogue is cached to :data:`CACHE_PATH`; if a later
    download fails (network down, registry outage) the cached copy is used with a warning, so
    a long-running study never breaks on a transient outage.

    Parameters
    ----------
    source : str, optional
        URL or local path to a ``systems.csv``. Defaults to :data:`DEFAULT_CATALOG_URL`
        (requires the optional ``[fetch]`` extra).
    timeout : int, default 30
        HTTP timeout in seconds (only when fetching a URL).
    use_cache : bool, default True
        Cache successful downloads and fall back to the cache on failure.

    Returns
    -------
    pandas.DataFrame
        The catalogue with normalised lowercase column names.
    """
    source = source or DEFAULT_CATALOG_URL
    if not source.startswith(("http://", "https://")):
        return _normalize_columns(pd.read_csv(source))

    import requests

    try:
        resp = requests.get(source, timeout=timeout, headers={"User-Agent": "gbfs-toolkit"})
        resp.raise_for_status()
        df = _normalize_columns(pd.read_csv(io.StringIO(resp.text)))
        if use_cache:
            try:
                CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
                CACHE_PATH.write_text(resp.text, encoding="utf-8")
            except OSError:  # pragma: no cover - caching is best-effort
                _log.debug("could not write catalogue cache to %s", CACHE_PATH)
        return df
    except (requests.RequestException, pd.errors.ParserError) as e:
        if use_cache and CACHE_PATH.exists():
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

"""Feed discovery — the global MobilityData systems catalogue and per-feed resolution.

The community registry of GBFS systems is MobilityData's ``systems.csv``. This
module loads it (from a URL or a local copy) into a tidy frame and resolves a
system's ``auto_discovery_url`` (the ``gbfs.json`` entry point).
"""

from __future__ import annotations

import io

import pandas as pd

#: MobilityData's canonical registry of GBFS systems.
DEFAULT_CATALOG_URL = "https://raw.githubusercontent.com/MobilityData/gbfs/master/systems.csv"


def systems_catalog(source: str | None = None, *, timeout: int = 30) -> pd.DataFrame:
    """Load the MobilityData systems catalogue.

    Parameters
    ----------
    source : str, optional
        URL or local path to a ``systems.csv``. Defaults to
        :data:`DEFAULT_CATALOG_URL` (requires the optional ``[fetch]`` extra).
    timeout : int, default 30
        HTTP timeout in seconds (only when fetching a URL).

    Returns
    -------
    pandas.DataFrame
        The catalogue with normalised lowercase column names.
    """
    source = source or DEFAULT_CATALOG_URL
    if source.startswith(("http://", "https://")):
        import requests

        resp = requests.get(source, timeout=timeout)
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text))
    else:
        df = pd.read_csv(source)
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    return df


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

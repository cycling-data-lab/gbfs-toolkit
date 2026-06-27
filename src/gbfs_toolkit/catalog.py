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

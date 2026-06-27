"""Normalise raw GBFS JSON into the canonical frames, across spec versions.

Handles the cross-version differences that every consumer otherwise re-implements:
GBFS 2.x exposes ``name`` as a plain string, GBFS 3.x as a localized array of
``{text, language}`` objects; vehicle feeds are ``free_bike_status`` (2.x) vs
``vehicle_status`` (3.x). Output always conforms to
:data:`~gbfs_toolkit.models.STATION_INFO_COLUMNS` etc.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from gbfs_toolkit.models import STATION_INFO_COLUMNS


def _name(value: Any) -> str | None:
    """GBFS 2.x string name, or GBFS 3.x localized [{text, language}] array."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, list) and value:
        first = value[0]
        if isinstance(first, dict):
            return first.get("text")
    return None


def _infer_station_type(station: dict) -> str:
    """Best-effort station semantics from a station_information record.

    GBFS does not carry an explicit dock/free-float/carshare flag, so we use a
    conservative heuristic: a virtual station, or one with no physical capacity,
    is treated as a free-floating anchor; everything else as a docked station.
    Callers with ground truth should set ``station_type`` themselves.
    """
    if station.get("is_virtual_station") or station.get("capacity") in (None, 0):
        return "free_floating"
    return "docked_bike"


def to_canonical_station_info(
    raw: dict,
    *,
    system_id: str,
    gbfs_version: str = "2.x",
    station_type: str | None = None,
) -> pd.DataFrame:
    """Parse a ``station_information.json`` document into a canonical frame.

    Parameters
    ----------
    raw : dict
        The parsed JSON of ``station_information`` (the full document, i.e.
        ``{"data": {"stations": [...]}, ...}``, or just the ``data`` mapping).
    system_id : str
        Identifier to stamp on every row.
    gbfs_version : str, default "2.x"
        Used only for the ``_name`` localisation heuristic and provenance.
    station_type : str, optional
        If given, force this type on all stations (overrides inference).

    Returns
    -------
    pandas.DataFrame
        Canonical station-information frame (:data:`STATION_INFO_COLUMNS`).
    """
    data = raw.get("data", raw)
    stations = data.get("stations", []) if isinstance(data, dict) else []
    rows = []
    for s in stations:
        rows.append(
            {
                "system_id": system_id,
                "station_id": str(s.get("station_id")),
                "name": _name(s.get("name")),
                "lat": s.get("lat"),
                "lon": s.get("lon"),
                "capacity": s.get("capacity"),
                "station_type": station_type or _infer_station_type(s),
            }
        )
    df = pd.DataFrame(rows, columns=STATION_INFO_COLUMNS)
    for col in ("lat", "lon", "capacity"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df

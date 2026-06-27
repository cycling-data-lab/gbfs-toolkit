"""Normalise raw GBFS JSON into the canonical frames, across spec versions.

Handles the cross-version differences that every consumer otherwise re-implements:
GBFS 2.x exposes ``name`` as a plain string, GBFS 3.x as a localized array of
``{text, language}`` objects; vehicle feeds are ``free_bike_status`` (2.x) vs
``vehicle_status`` (3.x). Output always conforms to
:data:`~gbfs_toolkit.core.models.STATION_INFO_COLUMNS` etc.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from gbfs_toolkit.core.models import (
    ALERT_COLUMNS,
    PRICING_PLAN_COLUMNS,
    STATION_INFO_COLUMNS,
    STATION_STATUS_COLUMNS,
    STATION_VEHICLE_COUNTS_COLUMNS,
    SYSTEM_REGION_COLUMNS,
    VEHICLE_STATUS_COLUMNS,
    VEHICLE_TYPE_COLUMNS,
)


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


def _records(data: Any, *keys: str) -> list:
    """Extract a list of records from a feed's ``data``, tolerating language nesting.

    Most feeds put the list at ``data.<key>`` (e.g. ``data.stations``), but some old GBFS
    1.x/2.x feeds nest it under a language key (``data.<lang>.<key>``). Tries the flat form
    first, then falls back to the first language sub-mapping that carries one of ``keys``.
    """
    if not isinstance(data, dict):
        return []
    for key in keys:
        value = data.get(key)
        if isinstance(value, list):
            return value
    for sub in data.values():
        if isinstance(sub, dict):
            for key in keys:
                value = sub.get(key)
                if isinstance(value, list):
                    return value
    return []


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
    stations = _records(data, "stations")
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
                "is_virtual_station": bool(s.get("is_virtual_station", False)),
                "region_id": s.get("region_id"),
            }
        )
    df = pd.DataFrame(rows, columns=STATION_INFO_COLUMNS)
    for col in ("lat", "lon", "capacity"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _utc(value: Any) -> pd.Timestamp:
    """Parse a GBFS timestamp to a tz-aware UTC ``Timestamp`` (NaT if unparseable).

    GBFS 2.x ``last_reported`` is unix seconds; GBFS 3.x is an RFC3339 string.
    """
    if value is None:
        return pd.NaT
    if isinstance(value, (int, float)):
        return pd.to_datetime(value, unit="s", utc=True)
    try:  # numeric strings still mean unix seconds
        return pd.to_datetime(float(value), unit="s", utc=True)
    except (TypeError, ValueError):
        return pd.to_datetime(value, errors="coerce", utc=True)


def _now_utc() -> pd.Timestamp:
    return pd.Timestamp.now(tz="UTC")


def to_canonical_station_status(
    raw: dict,
    *,
    system_id: str,
    gbfs_version: str = "2.x",
    fetched_at: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Parse a ``station_status.json`` document into a canonical frame.

    Returns :data:`~gbfs_toolkit.core.models.STATION_STATUS_COLUMNS`. ``fetched_at`` is a
    tz-aware UTC timestamp stamped on every row (defaults to *now*) for provenance.
    """
    fetched_at = fetched_at if fetched_at is not None else _now_utc()
    data = raw.get("data", raw)
    stations = _records(data, "stations")
    rows = [
        {
            "system_id": system_id,
            "station_id": str(s.get("station_id")),
            # GBFS 3.0 renamed num_bikes_available → num_vehicles_available; accept both.
            "num_bikes_available": (
                s["num_bikes_available"]
                if s.get("num_bikes_available") is not None
                else s.get("num_vehicles_available")
            ),
            # GBFS 3.0 also offers vehicle_docks_available alongside num_docks_available.
            "num_docks_available": (
                s["num_docks_available"]
                if s.get("num_docks_available") is not None
                else s.get("vehicle_docks_available")
            ),
            "is_renting": bool(s.get("is_renting", True)),
            "is_returning": bool(s.get("is_returning", True)),
            "is_installed": bool(s.get("is_installed", True)),
            "last_reported": _utc(s.get("last_reported")),
            "fetched_at": fetched_at,
            "gbfs_version": gbfs_version,
        }
        for s in stations
    ]
    df = pd.DataFrame(rows, columns=STATION_STATUS_COLUMNS)
    # Nullable extension dtypes so a later outer join (e.g. availability()) inserts
    # pd.NA without silently upcasting counts/flags to float and corrupting equality.
    for col in ("num_bikes_available", "num_docks_available"):
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    for col in ("is_renting", "is_returning", "is_installed"):
        df[col] = df[col].astype("boolean")
    for col in ("last_reported", "fetched_at"):
        df[col] = pd.to_datetime(df[col], utc=True)
    return df


def to_canonical_station_vehicle_counts(
    raw: dict,
    *,
    system_id: str,
    fetched_at: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Melt per-vehicle-type availability from ``station_status`` into a long frame.

    GBFS 2.2+/3.x stations may report ``vehicle_types_available`` (a list of
    ``{vehicle_type_id, count}``). This explodes it to one row per station × vehicle type
    (:data:`~gbfs_toolkit.core.models.STATION_VEHICLE_COUNTS_COLUMNS`), so "where are the e-bikes?"
    is a join to :func:`to_canonical_vehicle_types`; the aggregate ``num_bikes_available``
    cannot answer it. Stations without the field contribute no rows.
    """
    fetched_at = fetched_at if fetched_at is not None else _now_utc()
    data = raw.get("data", raw)
    stations = _records(data, "stations")
    rows = [
        {
            "system_id": system_id,
            "station_id": str(s.get("station_id")),
            "vehicle_type_id": str(vt.get("vehicle_type_id")),
            "num_vehicles_available": vt.get("count"),
            "fetched_at": fetched_at,
        }
        for s in stations
        for vt in (s.get("vehicle_types_available") or [])
    ]
    df = pd.DataFrame(rows, columns=STATION_VEHICLE_COUNTS_COLUMNS)
    df["num_vehicles_available"] = pd.to_numeric(
        df["num_vehicles_available"], errors="coerce"
    ).astype("Int64")
    df["fetched_at"] = pd.to_datetime(df["fetched_at"], utc=True)
    return df


def to_canonical_vehicles(
    raw: dict,
    *,
    system_id: str,
    gbfs_version: str = "2.x",
    fetched_at: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Parse ``free_bike_status`` (2.x) or ``vehicle_status`` (3.x) into a canonical frame.

    Returns :data:`~gbfs_toolkit.core.models.VEHICLE_STATUS_COLUMNS`.
    """
    fetched_at = fetched_at if fetched_at is not None else _now_utc()
    data = raw.get("data", raw)
    # v3 → "vehicles", v2 → "bikes" (tolerate language nesting)
    items = _records(data, "vehicles", "bikes")
    rows = [
        {
            "system_id": system_id,
            "vehicle_id": str(v.get("vehicle_id") or v.get("bike_id")),
            "station_id": (str(v["station_id"]) if v.get("station_id") is not None else None),
            "vehicle_type_id": v.get("vehicle_type_id"),
            "lat": v.get("lat"),
            "lon": v.get("lon"),
            "is_reserved": bool(v.get("is_reserved", False)),
            "is_disabled": bool(v.get("is_disabled", False)),
            "current_range_meters": v.get("current_range_meters"),
            "current_fuel_percent": v.get("current_fuel_percent"),  # GBFS 3.0 battery %
            "pricing_plan_id": v.get("pricing_plan_id"),
            "fetched_at": fetched_at,
            "gbfs_version": gbfs_version,
        }
        for v in items
    ]
    df = pd.DataFrame(rows, columns=VEHICLE_STATUS_COLUMNS)
    for col in ("lat", "lon", "current_range_meters", "current_fuel_percent"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in ("is_reserved", "is_disabled"):
        df[col] = df[col].astype("boolean")
    for col in ("station_id", "pricing_plan_id"):
        df[col] = df[col].astype("string")
    df["fetched_at"] = pd.to_datetime(df["fetched_at"], utc=True)
    return df


def to_canonical_vehicle_types(raw: dict, *, system_id: str) -> pd.DataFrame:
    """Parse ``vehicle_types.json`` into a canonical catalogue.

    Resolves ``VehicleStatus.vehicle_type_id`` to a form factor / propulsion, so
    "where are the e-bikes?" becomes a join. Returns
    :data:`~gbfs_toolkit.core.models.VEHICLE_TYPE_COLUMNS`.
    """
    data = raw.get("data", raw)
    types = _records(data, "vehicle_types")
    rows = [
        {
            "system_id": system_id,
            "vehicle_type_id": str(t.get("vehicle_type_id")),
            "form_factor": t.get("form_factor"),
            "propulsion_type": t.get("propulsion_type"),
            "max_range_meters": t.get("max_range_meters"),
        }
        for t in types
    ]
    df = pd.DataFrame(rows, columns=VEHICLE_TYPE_COLUMNS)
    df["max_range_meters"] = pd.to_numeric(df["max_range_meters"], errors="coerce")
    return df


def to_canonical_pricing_plans(raw: dict, *, system_id: str) -> pd.DataFrame:
    """Parse ``system_pricing_plans.json`` into a canonical lookup table.

    Resolves the ``pricing_plan_id`` foreign key carried on vehicles, so cost / equity
    studies can join price to availability. Returns
    :data:`~gbfs_toolkit.core.models.PRICING_PLAN_COLUMNS`; ``name``/``description`` are localised
    via the same v2/v3 heuristic as elsewhere.
    """
    data = raw.get("data", raw)
    plans = _records(data, "plans")
    rows = [
        {
            "system_id": system_id,
            "plan_id": str(p.get("plan_id")),
            "name": _name(p.get("name")),
            "currency": p.get("currency"),
            "price": p.get("price"),
            "is_taxable": p.get("is_taxable"),
            "description": _name(p.get("description")),
        }
        for p in plans
    ]
    df = pd.DataFrame(rows, columns=PRICING_PLAN_COLUMNS)
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df["is_taxable"] = df["is_taxable"].astype("boolean")
    return df


def to_canonical_system_regions(raw: dict, *, system_id: str) -> pd.DataFrame:
    """Parse ``system_regions.json`` into a canonical ``region_id → name`` lookup.

    Resolves the ``region_id`` foreign key carried on stations, so large multi-region
    networks can be subset or aggregated by region. Returns
    :data:`~gbfs_toolkit.core.models.SYSTEM_REGION_COLUMNS`.
    """
    data = raw.get("data", raw)
    regions = _records(data, "regions")
    rows = [
        {
            "system_id": system_id,
            "region_id": str(r.get("region_id")),
            "name": _name(r.get("name")),
        }
        for r in regions
    ]
    return pd.DataFrame(rows, columns=SYSTEM_REGION_COLUMNS)


def to_canonical_alerts(raw: dict, *, system_id: str) -> pd.DataFrame:
    """Parse ``system_alerts.json`` into a canonical alerts frame.

    Service disruptions (strikes, closures, weather) that explain anomalies in the data.
    Each alert's first time window is used for ``start``/``end`` (tz-aware UTC, NaT if
    open-ended). Returns :data:`~gbfs_toolkit.core.models.ALERT_COLUMNS`.
    """
    data = raw.get("data", raw)
    alerts = _records(data, "alerts")
    rows = []
    for a in alerts:
        times = a.get("times") or []
        first = times[0] if times and isinstance(times[0], dict) else {}
        rows.append(
            {
                "system_id": system_id,
                "alert_id": str(a.get("alert_id")),
                "type": a.get("type"),
                "summary": _name(a.get("summary")),
                "description": _name(a.get("description")),
                "start": _utc(first.get("start")),
                "end": _utc(first.get("end")),
                "last_updated": _utc(a.get("last_updated")),
            }
        )
    df = pd.DataFrame(rows, columns=ALERT_COLUMNS)
    for col in ("start", "end", "last_updated"):
        df[col] = pd.to_datetime(df[col], utc=True)
    return df


def to_canonical_system_information(raw: dict, *, system_id: str | None = None) -> dict[str, Any]:
    """Parse ``system_information.json`` into a small dict of system metadata.

    Crucially exposes ``timezone`` (e.g. ``"Europe/Paris"``) so UTC frames can be
    converted to local diurnal time without a manual lookup per city.
    """
    data = raw.get("data", raw)
    if not isinstance(data, dict):
        data = {}
    return {
        "system_id": str(data.get("system_id") or system_id or ""),
        "name": _name(data.get("name")),
        "timezone": data.get("timezone"),
        "language": data.get("language") or (data.get("languages") or [None])[0],
        "operator": _name(data.get("operator")),
        "url": data.get("url"),
    }

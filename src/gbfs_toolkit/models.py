"""Canonical data model for GBFS feeds: the stable contract every other module
(and every downstream research script) builds on.

The whole point of the toolkit is that *ingestion* (which varies across GBFS
1.x/2.x/3.x) is normalised once into these version-independent frames, and
*audit / panels* then operate purely on the canonical schema. Downstream code
should depend on these column names, never on raw GBFS JSON.
"""

from __future__ import annotations

import pandas as pd

from gbfs_toolkit.errors import GBFSValidationError

#: Canonical station-information columns (static inventory of a docked system).
STATION_INFO_COLUMNS: list[str] = [
    "system_id",
    "station_id",
    "name",
    "lat",
    "lon",
    "capacity",
    "station_type",  # one of STATION_TYPES
    "is_virtual_station",  # painted-box vs physical dock (GBFS 2.1+)
    "region_id",  # groups stations by city/zone in multi-region operators
]

#: Canonical vehicle-type catalogue (``vehicle_types.json``); resolves
#: ``VehicleStatus.vehicle_type_id`` to a form factor and propulsion.
VEHICLE_TYPE_COLUMNS: list[str] = [
    "system_id",
    "vehicle_type_id",
    "form_factor",  # bicycle / scooter / car / …
    "propulsion_type",  # human / electric_assist / electric / …
    "max_range_meters",
]

#: Canonical station-status columns (a timestamped availability snapshot).
#: ``last_reported`` and ``fetched_at`` are tz-aware UTC timestamps
#: (``datetime64[ns, UTC]``) so feeds from different cities merge unambiguously.
STATION_STATUS_COLUMNS: list[str] = [
    "system_id",
    "station_id",
    "num_bikes_available",
    "num_docks_available",
    "is_renting",  # station accepts rentals right now
    "is_returning",  # station accepts returns right now
    "is_installed",  # hardware physically deployed on the street (GBFS: distinct from is_renting)
    "last_reported",  # UTC datetime (feed-reported)
    "fetched_at",  # UTC datetime (when *we* fetched it)
    "gbfs_version",
]

#: Canonical free-floating vehicle-status columns.
VEHICLE_STATUS_COLUMNS: list[str] = [
    "system_id",
    "vehicle_id",
    "station_id",  # set when the vehicle is parked at a station (else NA → free-floating)
    "vehicle_type_id",  # pedal / e-bike / scooter (the key modern axis)
    "lat",
    "lon",
    "is_reserved",
    "is_disabled",
    "current_range_meters",  # remaining range: the core e-bike/battery research signal
    "current_fuel_percent",  # remaining battery as a 0–1 fraction (GBFS 3.0)
    "pricing_plan_id",  # preserved (not parsed) for equity / pricing joins
    "fetched_at",  # UTC datetime
    "gbfs_version",
]

#: Canonical geofencing-zone columns (``geofencing_zones.json``); operator-defined
#: service-area polygons. ``geometry`` holds a shapely (Multi)Polygon (EPSG:4326); the
#: boolean/speed fields summarise the zone's *default* rule, with the full ``rules`` list
#: preserved for per-vehicle-type detail. Requires the optional ``[geo]`` extra.
GEOFENCING_COLUMNS: list[str] = [
    "system_id",
    "zone_id",
    "name",
    "ride_allowed",  # may a trip pass through / operate here (default rule)
    "ride_through_allowed",
    "maximum_speed_kph",
    "station_parking",  # parking only at stations within this zone
    "rules",  # full list of per-vehicle-type rule dicts (unparsed)
    "geometry",
]

#: Canonical per-vehicle-type availability at docked stations (GBFS 2.2+/3.x
#: ``vehicle_types_available``): *melted* (long), one row per station × vehicle type.
#: ``num_bikes_available`` aggregates these; this schema preserves the breakdown so
#: "where are the e-bikes?" is answerable. Joins to :data:`VEHICLE_TYPE_COLUMNS`.
STATION_VEHICLE_COUNTS_COLUMNS: list[str] = [
    "system_id",
    "station_id",
    "vehicle_type_id",
    "num_vehicles_available",
    "fetched_at",  # UTC datetime
]

#: Canonical pricing-plan lookup (``system_pricing_plans.json``); resolves the
#: ``pricing_plan_id`` foreign key carried on vehicles, for equity / cost research.
PRICING_PLAN_COLUMNS: list[str] = [
    "system_id",
    "plan_id",
    "name",
    "currency",
    "price",  # base price (the plan's headline amount)
    "is_taxable",
    "description",
]

#: Canonical region lookup (``system_regions.json``); resolves the ``region_id`` foreign key
#: carried on stations, so large multi-region networks can be subset/aggregated by region name.
SYSTEM_REGION_COLUMNS: list[str] = [
    "system_id",
    "region_id",
    "name",
]

#: Canonical service alerts (``system_alerts.json``): disruptions that explain anomalies in
#: the data (a strike, a closure, a weather event). ``start``/``end`` are tz-aware UTC.
ALERT_COLUMNS: list[str] = [
    "system_id",
    "alert_id",
    "type",  # SYSTEM_CLOSURE / STATION_CLOSURE / STATION_MOVE / OTHER …
    "summary",
    "description",
    "start",  # UTC datetime (NaT if open-ended)
    "end",  # UTC datetime (NaT if open-ended)
    "last_updated",  # UTC datetime
]

#: Station semantics recognised by the audit (drives A1/A3).
STATION_TYPES: tuple[str, ...] = ("docked_bike", "free_floating", "carsharing")

# ---------------------------------------------------------------------------
# The semantic-audit taxonomy (Fossé & Pallares, gbfs-audit-catalogue).
# Row-level: A1, A3, A4 (this particular station).
# System-level: A2, A5, A6, A7 (every row of a flagged system carries the flag).
# ---------------------------------------------------------------------------

AUDIT_FLAGS: tuple[str, ...] = ("A1", "A2", "A3", "A4", "A5", "A6", "A7")

RULES: dict[str, dict[str, str]] = {
    "A1": {
        "name": "Out-of-domain inclusion",
        "signature": "car-sharing advertised as a bike-sharing system",
    },
    "A2": {
        "name": "Placeholder capacity",
        "signature": "constant non-zero capacity across every station of a system",
    },
    "A3": {
        "name": "Structural over-capacity",
        "signature": "conditional averaging on free-floating fleet anchors",
    },
    "A4": {
        "name": "Geospatial error",
        "signature": "transposed coordinates or stations beyond 3 sigma from neighbours",
    },
    "A5": {
        "name": "Out-of-perimeter coverage",
        "signature": "system bounding box > 50,000 km2 or out-of-jurisdiction stations",
    },
    "A6": {
        "name": "Zero-capacity dock",
        "signature": "at least 1% of stations declare capacity = 0",
    },
    "A7": {
        "name": "Null capacity field",
        "signature": "at least 50% of stations declare capacity = NaN",
    },
}

# Thresholds (kept identical to the published catalogue so verdicts reproduce).
A2_MIN_STATIONS = 20
A4_MIN_STATIONS = 5
A4_SIGMA = 3.0
A4_MIN_THRESHOLD_M = 1_000.0
A5_BBOX_MAX_KM2 = 50_000.0
A6_RATE_THRESHOLD = 0.01
A6_MIN_STATIONS = 20
A7_RATE_THRESHOLD = 0.50
A7_MIN_STATIONS = 20


class SchemaError(GBFSValidationError, ValueError):
    """Raised when a frame does not satisfy the canonical schema.

    Subclasses both :class:`~gbfs_toolkit.errors.GBFSValidationError` (so
    ``except GBFSError`` catches it) and :class:`ValueError` (backward compatibility).

    For schema-mismatch cases the exception also carries structured fields, so an
    automated pipeline can branch on them without parsing the message: ``missing`` (the
    absent columns), ``present`` (the columns that were supplied), and ``what`` (the
    operation that required them). They are ``None`` for other validation failures.
    """

    def __init__(
        self,
        message: str,
        *,
        missing: list[str] | None = None,
        present: list[str] | None = None,
        what: str | None = None,
    ) -> None:
        super().__init__(message)
        self.missing = missing
        self.present = present
        self.what = what


#: Canonical data-model reference, cited in schema-error messages.
_DATA_MODEL_URL = "https://cycling-data-lab.github.io/gbfs-toolkit/data-model/"


def require_columns(df: pd.DataFrame, columns: list[str], *, what: str) -> None:
    """Raise a didactic :class:`SchemaError` if ``df`` is missing any of ``columns``.

    The message names the missing columns, lists the columns that were present, gives the
    likely cause, and points to a concrete fix, so the most common user error (passing a
    frame that did not come from a ``to_canonical_*`` normaliser) explains itself.
    """
    missing = [c for c in columns if c not in df.columns]
    if not missing:
        return
    present = list(df.columns)
    message = (
        f"{what}: missing required column(s) {missing}.\n"
        f"  present columns: {present}\n"
        f"  likely cause: this frame did not come from a to_canonical_* normaliser, or an "
        f"optional GBFS field is absent for this system.\n"
        f"  fix: normalise the raw feed with the matching to_canonical_* function, or add the "
        f"column(s) before calling. Canonical schema: {_DATA_MODEL_URL}"
    )
    raise SchemaError(message, missing=missing, present=present, what=what)


#: Named canonical schemas (column contracts) addressable by :func:`validate_schema`.
SCHEMAS: dict[str, list[str]] = {
    "station_info": STATION_INFO_COLUMNS,
    "station_status": STATION_STATUS_COLUMNS,
    "station_vehicle_counts": STATION_VEHICLE_COUNTS_COLUMNS,
    "vehicle_status": VEHICLE_STATUS_COLUMNS,
    "vehicle_types": VEHICLE_TYPE_COLUMNS,
    "pricing_plans": PRICING_PLAN_COLUMNS,
    "geofencing": GEOFENCING_COLUMNS,
    "system_regions": SYSTEM_REGION_COLUMNS,
    "alerts": ALERT_COLUMNS,
}

# Canonical dtype of each column, used by coerce_schema (datetimes handled separately).
_CANONICAL_DTYPES: dict[str, str] = {
    "lat": "float64",
    "lon": "float64",
    "capacity": "Int64",
    "num_bikes_available": "Int64",
    "num_docks_available": "Int64",
    "num_vehicles_available": "Int64",
    "current_range_meters": "float64",
    "max_range_meters": "float64",
    "price": "float64",
    "is_renting": "boolean",
    "is_returning": "boolean",
    "is_installed": "boolean",
    "is_virtual_station": "boolean",
    "is_reserved": "boolean",
    "is_disabled": "boolean",
    "is_taxable": "boolean",
}
_DATETIME_COLUMNS = frozenset({"last_reported", "fetched_at", "start", "end", "last_updated"})


def _schema_columns(schema: str) -> list[str]:
    if schema not in SCHEMAS:
        raise SchemaError(
            f"unknown schema {schema!r}; choose from {sorted(SCHEMAS)}. "
            f"These are the named canonical contracts in models.SCHEMAS."
        )
    return SCHEMAS[schema]


def validate_schema(df: pd.DataFrame, schema: str) -> pd.DataFrame:
    """Assert a frame still obeys a canonical schema, then return it (for chaining).

    Use after slicing/grouping/mutating a canonical frame (e.g. before appending to the
    Parquet lake) to fail fast with a clear :class:`SchemaError` instead of corrupting the
    dataset. ``schema`` is one of :data:`SCHEMAS` (``"station_status"``, ``"vehicle_status"``…).
    """
    require_columns(df, _schema_columns(schema), what=f"validate_schema({schema!r})")
    return df


def coerce_schema(df: pd.DataFrame, schema: str) -> pd.DataFrame:
    """Cast a frame's columns to the canonical dtypes for ``schema`` (nullable ints/bools, UTC).

    Best-effort: only columns present are touched; unparseable values become ``pd.NA``/``NaT``.
    Handy after reading frames from CSV or a third-party source before feeding the toolkit.
    """
    out = df.copy()
    for col in _schema_columns(schema):
        if col not in out.columns:
            continue
        if col in _DATETIME_COLUMNS:
            out[col] = pd.to_datetime(out[col], utc=True, errors="coerce")
        elif col in _CANONICAL_DTYPES:
            dtype = _CANONICAL_DTYPES[col]
            if dtype in ("Int64", "float64"):
                out[col] = pd.to_numeric(out[col], errors="coerce").astype(dtype)
            else:
                out[col] = out[col].astype(dtype)
    return out

"""Canonical data model for GBFS feeds — the stable contract every other module
(and every downstream research script) builds on.

The whole point of the toolkit is that *ingestion* (which varies across GBFS
1.x/2.x/3.x) is normalised once into these version-independent frames, and
*audit / panels* then operate purely on the canonical schema. Downstream code
should depend on these column names, never on raw GBFS JSON.
"""

from __future__ import annotations

import pandas as pd

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

#: Canonical vehicle-type catalogue (``vehicle_types.json``) — resolves
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
    "last_reported",  # UTC datetime (feed-reported)
    "fetched_at",  # UTC datetime (when *we* fetched it)
    "gbfs_version",
]

#: Canonical free-floating vehicle-status columns.
VEHICLE_STATUS_COLUMNS: list[str] = [
    "system_id",
    "vehicle_id",
    "vehicle_type_id",  # pedal / e-bike / scooter (the key modern axis)
    "lat",
    "lon",
    "is_reserved",
    "is_disabled",
    "fetched_at",  # UTC datetime
    "gbfs_version",
]

#: Station semantics recognised by the audit (drives A1/A3).
STATION_TYPES: tuple[str, ...] = ("docked_bike", "free_floating", "carsharing")

# ---------------------------------------------------------------------------
# The semantic-audit taxonomy (Fossé & Pallares, gbfs-audit-catalogue).
# Row-level: A1, A3, A4 — this particular station.
# System-level: A2, A5, A6, A7 — every row of a flagged system carries the flag.
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


class SchemaError(ValueError):
    """Raised when a frame does not satisfy the canonical schema."""


def require_columns(df: pd.DataFrame, columns: list[str], *, what: str) -> None:
    """Raise :class:`SchemaError` if ``df`` is missing any of ``columns``."""
    missing = [c for c in columns if c not in df.columns]
    if missing:
        raise SchemaError(f"{what}: missing required columns {missing}; got {list(df.columns)}")

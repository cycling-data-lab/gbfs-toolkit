"""Semantic audit of GBFS feeds (the toolkit's flagship)."""

from __future__ import annotations

import pandas as pd

from gbfs_toolkit.audit.catalogue import audit_catalogue
from gbfs_toolkit.audit.dynamic import audit_dynamic
from gbfs_toolkit.audit.static import (
    audit_sensitivity,
    audit_static,
    capacity_convention,
    classify_from_vehicle_types,
    classify_from_virtual_station,
    flag_rate_ci,
    flag_sentinel_coordinates,
    overcapacity_ratio,
    reclassify_overcapacity,
)

#: Stacked-audit columns shared by static and dynamic verdicts.
AUDIT_RESULT_COLUMNS = ["system_id", "station_id", "audit_type", "flagged", "reason"]


def audit_frames(
    info: pd.DataFrame,
    status: pd.DataFrame | None = None,
    *,
    ttl_seconds: int | None = None,
    system_id: str = "system",
) -> pd.DataFrame:
    """Unified semantic audit on canonical frames: static (A1–A7) and, if given, dynamic (D1–D3).

    A pure function (no feed object), so it audits feeds you fetched yourself *or* frames read
    back from a Parquet lake. Results are stacked with an ``audit_type`` column. Use
    :func:`audit_static` / :func:`audit_dynamic` directly for the per-rule boolean columns.

    See Also
    --------
    [`audit_static`][gbfs_toolkit.audit_static] : The static A1-A7 half, with per-rule boolean columns.
    [`audit_dynamic`][gbfs_toolkit.audit_dynamic] : The dynamic D1-D3 half, with per-rule boolean columns.
    [`drop_flagged`][gbfs_toolkit.drop_flagged] : Keep only the stations that pass the static audit.

    Examples
    --------
    >>> import pandas as pd
    >>> info = pd.DataFrame({
    ...     "system_id": "s", "station_id": ["a", "b"],
    ...     "station_type": ["docked_bike", "carsharing"],
    ...     "capacity": [20, 5], "lat": [48.85, 48.86], "lon": [2.35, 2.36],
    ... })
    >>> audit_frames(info)[["station_id", "audit_type", "flagged"]]  # doctest: +NORMALIZE_WHITESPACE
      station_id audit_type  flagged
    0          a     static    False
    1          b     static     True
    """
    static = audit_static(info).assign(audit_type="static")
    parts = [static[AUDIT_RESULT_COLUMNS]]
    if status is not None and len(status):
        from gbfs_toolkit.analytics.frames import join_availability

        availability = join_availability(info, status)
        dynamic = audit_dynamic(availability, ttl_seconds=ttl_seconds).assign(
            audit_type="dynamic", system_id=system_id
        )
        parts.append(dynamic[AUDIT_RESULT_COLUMNS])
    return pd.concat(parts, ignore_index=True)


def drop_flagged(stations: pd.DataFrame) -> pd.DataFrame:
    """The analysis-ready subset: stations that pass the static A1–A7 audit, in one call.

    Shorthand for running :func:`audit_static` and keeping the unflagged rows: the first thing
    most studies do before anything else.

    See Also
    --------
    [`audit_static`][gbfs_toolkit.audit_static] : The audit whose ``flagged`` column this filters on.
    [`audit_frames`][gbfs_toolkit.audit_frames] : Run the static and dynamic audits and stack their verdicts.

    Examples
    --------
    The car-sharing station (A1) is dropped; the docked station survives:

    >>> import pandas as pd
    >>> stations = pd.DataFrame({
    ...     "system_id": "s", "station_id": ["a", "b"],
    ...     "station_type": ["docked_bike", "carsharing"],
    ...     "capacity": [20, 5], "lat": [48.85, 48.86], "lon": [2.35, 2.36],
    ... })
    >>> drop_flagged(stations)["station_id"].tolist()
    ['a']
    """
    verdict = audit_static(stations)
    return stations[~verdict["flagged"].to_numpy()].reset_index(drop=True)


__all__ = [
    "audit_static",
    "audit_catalogue",
    "audit_sensitivity",
    "flag_rate_ci",
    "overcapacity_ratio",
    "reclassify_overcapacity",
    "classify_from_vehicle_types",
    "classify_from_virtual_station",
    "capacity_convention",
    "flag_sentinel_coordinates",
    "audit_dynamic",
    "audit_frames",
    "drop_flagged",
    "AUDIT_RESULT_COLUMNS",
]

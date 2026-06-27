"""Semantic audit of GBFS feeds (the toolkit's flagship)."""

from __future__ import annotations

import pandas as pd

from gbfs_toolkit.audit.dynamic import audit_dynamic
from gbfs_toolkit.audit.static import audit_static

#: Stacked-audit columns shared by static and dynamic verdicts.
AUDIT_RESULT_COLUMNS = ["system_id", "station_id", "audit_type", "flagged", "reason"]


def audit_frames(
    info: pd.DataFrame,
    status: pd.DataFrame | None = None,
    *,
    ttl_seconds: int | None = None,
    system_id: str = "system",
) -> pd.DataFrame:
    """Unified semantic audit on canonical frames — static (A1–A7) and, if given, dynamic (D1–D3).

    A pure function (no feed object), so it audits feeds you fetched yourself *or* frames read
    back from a Parquet lake. Results are stacked with an ``audit_type`` column. Use
    :func:`audit_static` / :func:`audit_dynamic` directly for the per-rule boolean columns.
    """
    static = audit_static(info).assign(audit_type="static")
    parts = [static[AUDIT_RESULT_COLUMNS]]
    if status is not None and len(status):
        from gbfs_toolkit.analysis import join_availability

        availability = join_availability(info, status)
        dynamic = audit_dynamic(availability, ttl_seconds=ttl_seconds).assign(
            audit_type="dynamic", system_id=system_id
        )
        parts.append(dynamic[AUDIT_RESULT_COLUMNS])
    return pd.concat(parts, ignore_index=True)


__all__ = ["audit_static", "audit_dynamic", "audit_frames", "AUDIT_RESULT_COLUMNS"]

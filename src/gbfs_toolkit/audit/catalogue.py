"""Batch audit of many GBFS systems in one call (fetch + A1-A7 + per-system status).

The high-level counterpart to :func:`~gbfs_toolkit.audit_static`: instead of one
in-memory frame, give it a list of MobilityData ``system_id`` values (and a
catalogue) and it fetches every reachable ``station_information``, audits the
union with the same function, and reports a per-system status so dead or empty
feeds are accounted for rather than silently dropped.

Heuristic-free: station types are taken from the feeds as declared. Operator-name
classification (car-sharing identification, free-floating reclassification) is a
separate, opt-in concern, not baked in here.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from gbfs_toolkit.audit.static import audit_static

_REQUIRED = ["system_id", "station_id", "station_type", "capacity", "lat", "lon"]


def audit_catalogue(
    system_ids: list[str],
    *,
    catalog: pd.DataFrame | None = None,
    a7_scope: str = "docked",
    max_workers: int = 8,
    **audit_kwargs: Any,
) -> tuple[pd.DataFrame, dict[str, str]]:
    """Fetch and audit many systems with one call.

    Parameters
    ----------
    system_ids : list[str]
        MobilityData system identifiers to fetch and audit.
    catalog : pandas.DataFrame, optional
        Systems catalogue used to resolve discovery URLs (see
        :func:`~gbfs_toolkit.systems_catalog`). Resolved from the default catalogue
        when omitted.
    a7_scope : {"docked", "all"}, default "docked"
        Passed through to :func:`audit_static`.
    max_workers : int, default 8
        Concurrency for the fetch stage.
    **audit_kwargs
        Forwarded to :func:`audit_static` (``a4_sigma``, ``a6_tau``, ``a7_tau``,
        ``a5_area_km2``, ``n_min``).

    Returns
    -------
    (verdict, status) : tuple[pandas.DataFrame, dict[str, str]]
        ``verdict`` is the per-station A1-A7 audit over every reachable system
        (empty if none reachable). ``status`` maps each ``system_id`` to one of
        ``"ok: N stations"``, ``"unreachable: <error>"``,
        ``"no station_information: <error>"``, ``"empty"`` or ``"missing columns"``.

    See Also
    --------
    [`audit_static`][gbfs_toolkit.audit_static] : The single-frame audit this batches over many fetched systems.
    [`audit_frames`][gbfs_toolkit.audit_frames] : Audit one system's static and dynamic frames you already hold.
    [`fetch_multiple`][gbfs_toolkit.fetch_multiple] : The concurrent fetch stage underneath this batch audit.
    """
    from gbfs_toolkit.io.fetch import fetch_multiple  # lazy: io.fetch imports audit

    feeds = fetch_multiple(list(system_ids), catalog=catalog, max_workers=max_workers)
    rows: list[pd.DataFrame] = []
    status: dict[str, str] = {}
    for sid, feed in feeds.items():
        if isinstance(feed, Exception):
            status[sid] = f"unreachable: {type(feed).__name__}"
            continue
        try:
            info = feed.station_information()
        except Exception as exc:  # noqa: BLE001  (any feed-shape failure is a drop)
            status[sid] = f"no station_information: {type(exc).__name__}"
            continue
        if info is None or len(info) == 0:
            status[sid] = "empty"
            continue
        if not set(_REQUIRED).issubset(info.columns):
            status[sid] = "missing columns"
            continue
        rows.append(info[_REQUIRED])
        status[sid] = f"ok: {len(info)} stations"
    frame = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=_REQUIRED)
    verdict = (
        audit_static(frame, a7_scope=a7_scope, **audit_kwargs)
        if len(frame)
        else pd.DataFrame(columns=["system_id", "station_id", *[f"A{i}" for i in range(1, 8)]])
    )
    return verdict, status

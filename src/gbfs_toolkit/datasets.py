"""Bundled example data — for docs, tutorials, doctests and offline tests.

A tiny, deterministic GBFS snapshot (a handful of central-Paris stations) so the README and
notebooks run in seconds without hitting a live operator feed. Parsed through the real
``to_canonical_*`` path, so it exercises the same normalisation as production data.
"""

from __future__ import annotations

import pandas as pd

from gbfs_toolkit.normalize import to_canonical_station_info, to_canonical_station_status

# (station_id, name, lat, lon, capacity, bikes, docks) — central Paris, hand-written.
_PARIS = [
    ("16107", "Benjamin Godard - Victor Hugo", 48.865983, 2.275725, 35, 4, 31),
    ("9020", "Toudouze - Clauzel", 48.879406, 2.337446, 21, 18, 2),
    ("7002", "Saint-Dominique - Bosquet", 48.858446, 2.304768, 28, 0, 28),
    ("11104", "Charonne - Robert et Sonia Delaunay", 48.855908, 2.388147, 20, 11, 9),
    ("12109", "Mairie du 12e", 48.840855, 2.387555, 30, 27, 3),
    ("5001", "Harpe - Saint-Germain", 48.852713, 2.343079, 25, 13, 12),
    ("18034", "Custine - Mont-Cenis", 48.890459, 2.345287, 22, 2, 20),
    ("14014", "Daguerre - Gaité", 48.838328, 2.323737, 18, 9, 9),
]

_INFO_DOC = {
    "data": {
        "stations": [
            {"station_id": s, "name": n, "lat": lat, "lon": lon, "capacity": cap}
            for s, n, lat, lon, cap, _b, _d in _PARIS
        ]
    }
}
# last_reported a few minutes before the canonical example fetch time.
_LAST_REPORTED = 1_767_600_000  # 2026-01-05T07:?? UTC, fixed for determinism
_STATUS_DOC = {
    "data": {
        "stations": [
            {
                "station_id": s,
                "num_bikes_available": b,
                "num_docks_available": d,
                "last_reported": _LAST_REPORTED,
            }
            for s, _n, _lat, _lon, _cap, b, d in _PARIS
        ]
    }
}

DATASETS: tuple[str, ...] = ("paris",)


def load_example(
    name: str = "paris", *, fetched_at: pd.Timestamp | str | None = None
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return a small canonical ``(station_info, station_status)`` pair for examples.

    >>> import gbfs_toolkit as gb
    >>> info, status = gb.load_example()
    >>> len(info), len(status)
    (8, 8)

    Parameters
    ----------
    name : str, default "paris"
        Dataset id (see :data:`DATASETS`).
    fetched_at : optional
        Fetch timestamp stamped on the status frame (default: a fixed 2026-01-05 08:00 UTC, so
        results are deterministic for doctests).
    """
    if name not in DATASETS:
        raise ValueError(f"unknown dataset {name!r}; choose from {list(DATASETS)}")
    ts = (
        pd.Timestamp(fetched_at) if fetched_at is not None else pd.Timestamp("2026-01-05T08:00:00Z")
    )
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    info = to_canonical_station_info(_INFO_DOC, system_id=name)
    status = to_canonical_station_status(_STATUS_DOC, system_id=name, fetched_at=ts)
    return info, status

"""Derived, ready-to-use metrics on canonical availability frames.

Small, safe, broadly-applicable transforms that every analysis re-implements —
deliberately *not* trip/OD inference (left to dedicated research code).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

#: Ordered categories returned by :func:`station_state`.
STATION_STATES = ("disabled", "virtual", "empty", "full", "normal")

#: Ordered categories of the ``presence`` indicator from :func:`join_availability`.
PRESENCE_STATES = ("both", "info_only", "status_only")


def join_availability(info: pd.DataFrame, status: pd.DataFrame) -> pd.DataFrame:
    """Join a status snapshot onto the station inventory — the analysis-ready availability frame.

    A pure function on canonical frames (no feed object needed), so it works equally on live
    data and on frames read back from a Parquet lake. Uses an **outer** join — operators
    routinely add/drop a station from one endpoint mid-sync — with a ``presence`` indicator
    (Categorical ``both`` / ``info_only`` / ``status_only``) so orphaned rows stay visible
    instead of being silently dropped.

    Parameters
    ----------
    info : pandas.DataFrame
        Canonical station information (:data:`~gbfs_toolkit.models.STATION_INFO_COLUMNS`).
    status : pandas.DataFrame
        Canonical station status (:data:`~gbfs_toolkit.models.STATION_STATUS_COLUMNS`).
    """
    info_cols = info.drop(columns=["system_id"]) if "system_id" in info.columns else info
    merged = status.merge(
        info_cols, on="station_id", how="outer", suffixes=("", "_info"), indicator="presence"
    )
    mapped = merged["presence"].map(
        {"both": "both", "left_only": "status_only", "right_only": "info_only"}
    )
    merged["presence"] = pd.Categorical(mapped, categories=list(PRESENCE_STATES))
    return merged


def station_state(availability: pd.DataFrame) -> pd.Series:
    """Classify each station as ``disabled`` / ``virtual`` / ``empty`` / ``full`` / ``normal``.

    Resolves two edge cases researchers re-derive constantly:
    an ``is_renting=False`` (and not returning) station is *disabled*, not merely empty;
    a *virtual* station (painted box, capacity 0/NA) must not be read as "full" just
    because it reports zero docks.

    Parameters
    ----------
    availability : pandas.DataFrame
        Needs ``num_bikes_available`` and ``num_docks_available``; uses
        ``is_renting`` / ``is_returning`` / ``is_virtual_station`` / ``capacity`` when present.

    Returns
    -------
    pandas.Series
        Categorical (categories = :data:`STATION_STATES`), aligned to the input index.
    """
    n = len(availability)
    bikes = (
        pd.to_numeric(availability["num_bikes_available"], errors="coerce").fillna(-1).to_numpy()
    )
    docks = (
        pd.to_numeric(availability["num_docks_available"], errors="coerce").fillna(-1).to_numpy()
    )

    def _bool(col: str, default: bool) -> np.ndarray:
        if col in availability:
            return availability[col].astype("boolean").fillna(default).to_numpy()
        return np.full(n, default, dtype=bool)

    renting = _bool("is_renting", True)
    returning = _bool("is_returning", True)
    is_virtual = _bool("is_virtual_station", False)
    if "capacity" in availability:
        cap = pd.to_numeric(availability["capacity"], errors="coerce").to_numpy()
        is_virtual = is_virtual | ~(cap > 0)  # no physical docks ⇒ treat as virtual

    state = np.where(
        ~renting & ~returning,
        "disabled",
        np.where(
            is_virtual,
            "virtual",
            np.where(bikes <= 0, "empty", np.where(docks <= 0, "full", "normal")),
        ),
    )
    return pd.Series(
        pd.Categorical(state, categories=list(STATION_STATES)),
        index=availability.index,
        name="station_state",
    )

"""Derived, ready-to-use metrics on canonical availability frames.

Small, safe, broadly-applicable transforms that every analysis re-implements —
deliberately *not* trip/OD inference (left to dedicated research code).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

#: Ordered categories returned by :func:`station_state`.
STATION_STATES = ("disabled", "empty", "full", "normal")


def station_state(availability: pd.DataFrame) -> pd.Series:
    """Classify each station as ``disabled`` / ``empty`` / ``full`` / ``normal``.

    Resolves the edge case researchers re-derive constantly: an ``is_renting=False``
    station is *disabled*, not merely empty, even if it reports zero bikes.

    Parameters
    ----------
    availability : pandas.DataFrame
        Needs ``num_bikes_available`` and ``num_docks_available``; uses
        ``is_renting`` / ``is_returning`` when present.

    Returns
    -------
    pandas.Series
        Categorical (categories = :data:`STATION_STATES`), aligned to the input index.
    """
    bikes = pd.to_numeric(availability["num_bikes_available"], errors="coerce")
    docks = pd.to_numeric(availability["num_docks_available"], errors="coerce")
    renting = (
        availability["is_renting"].astype("boolean")
        if "is_renting" in availability
        else pd.Series(True, index=availability.index)
    )
    returning = (
        availability["is_returning"].astype("boolean")
        if "is_returning" in availability
        else pd.Series(True, index=availability.index)
    )

    state = np.where(
        ~(renting.fillna(True).to_numpy()) & ~(returning.fillna(True).to_numpy()),
        "disabled",
        np.where(
            bikes.fillna(-1).to_numpy() <= 0,
            "empty",
            np.where(docks.fillna(-1).to_numpy() <= 0, "full", "normal"),
        ),
    )
    return pd.Series(
        pd.Categorical(state, categories=list(STATION_STATES)),
        index=availability.index,
        name="station_state",
    )

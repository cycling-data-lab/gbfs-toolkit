"""Derived, ready-to-use metrics on canonical availability frames.

Small, safe, broadly-applicable transforms that every analysis re-implements —
deliberately *not* trip/OD inference (left to dedicated research code).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from gbfs_toolkit.geo import haversine_m
from gbfs_toolkit.models import require_columns

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
    require_columns(info, ["station_id"], what="join_availability(info)")
    require_columns(status, ["station_id"], what="join_availability(status)")
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


_CHANGE_COLUMNS = ["system_id", "station_id", "change", "old_value", "new_value", "distance_m"]


def network_changes(
    old: pd.DataFrame, new: pd.DataFrame, *, move_threshold_m: float = 50.0
) -> pd.DataFrame:
    """Diff two station inventories — how the network itself changed between two dates.

    A multi-month study spans network growth, not a fixed graph. This compares two canonical
    ``station_information`` frames and reports stations **added**, **removed**,
    **recapacitated** (capacity changed) and **moved** (relocated beyond ``move_threshold_m``).
    A station can appear twice (e.g. recapacitated *and* moved).

    Returns
    -------
    pandas.DataFrame
        ``system_id, station_id, change, old_value, new_value, distance_m`` — ``old/new_value``
        carry the capacity for recapacitations; ``distance_m`` the move distance for moves.
    """
    require_columns(old, ["station_id"], what="network_changes(old)")
    require_columns(new, ["station_id"], what="network_changes(new)")
    o = old.drop_duplicates("station_id").set_index("station_id")
    n = new.drop_duplicates("station_id").set_index("station_id")
    sys_new = new["system_id"].iloc[0] if "system_id" in new.columns and len(new) else None

    rows = []

    def _row(sid, change, **kw):
        src = n if sid in n.index else o
        system = src.loc[sid, "system_id"] if "system_id" in src.columns else sys_new
        rows.append({"system_id": system, "station_id": sid, "change": change, **kw})

    for sid in n.index.difference(o.index):
        _row(sid, "added")
    for sid in o.index.difference(n.index):
        _row(sid, "removed")

    common = o.index.intersection(n.index)
    if len(common):
        oc, nc = o.loc[common], n.loc[common]
        if "capacity" in oc.columns and "capacity" in nc.columns:
            changed = oc["capacity"].ne(nc["capacity"]) & ~(
                oc["capacity"].isna() & nc["capacity"].isna()
            )
            for sid in common[changed.to_numpy()]:
                _row(
                    sid,
                    "recapacitated",
                    old_value=oc.at[sid, "capacity"],
                    new_value=nc.at[sid, "capacity"],
                )
        if {"lat", "lon"} <= set(oc.columns) & set(nc.columns):
            dist = pd.Series(haversine_m(oc["lat"], oc["lon"], nc["lat"], nc["lon"]), index=common)
            for sid in common[(dist > move_threshold_m).to_numpy()]:
                _row(sid, "moved", distance_m=round(float(dist[sid]), 1))

    return pd.DataFrame(rows, columns=_CHANGE_COLUMNS).reset_index(drop=True)


def join_vehicle_types(vehicles: pd.DataFrame, vehicle_types: pd.DataFrame) -> pd.DataFrame:
    """Resolve ``vehicle_type_id`` → form factor / propulsion / range onto a vehicles frame.

    Turns "where are the e-bikes?" into a filter: ``out[out.form_factor == "bicycle"]`` etc.
    Left join on ``vehicle_type_id``; the catalogue's ``system_id`` is dropped to avoid a clash.
    """
    cat = vehicle_types.drop(columns=["system_id"], errors="ignore")
    return vehicles.merge(cat, on="vehicle_type_id", how="left")


def join_pricing(vehicles: pd.DataFrame, plans: pd.DataFrame) -> pd.DataFrame:
    """Resolve ``pricing_plan_id`` → plan name / price / currency onto a vehicles frame.

    Left join of :func:`~gbfs_toolkit.to_canonical_pricing_plans` (its ``plan_id`` matches the
    vehicle's ``pricing_plan_id``); plan ``name``/``description`` are prefixed ``plan_`` to
    avoid clashes.
    """
    p = plans.drop(columns=["system_id"], errors="ignore").rename(
        columns={
            "plan_id": "pricing_plan_id",
            "name": "plan_name",
            "description": "plan_description",
        }
    )
    return vehicles.merge(p, on="pricing_plan_id", how="left")

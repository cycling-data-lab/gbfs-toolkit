"""Follow stations from one period (or source) to the next when their identifiers change.

!!! warning "Experimental"
    Part of the experimental data-lake modules added in 2.1.0: names, parameters and output
    columns may change in a minor release (see the API policy).

Operators renumber stations, re-issue identifiers when they change platform, and move a dock
a few metres. A study that spans two periods needs to know which station of the first is which
of the second. :func:`match_stations` pairs them **one to one**, in three passes, and says
which rule made each pair, so you can keep the safe pairs and look at the others:

1. ``same_id``: the identifier exists in both. If the two coordinates are more than
   ``same_id_far_m`` apart the pair is labelled ``same_id_far`` instead (same id, probably
   not the same place: check it).
2. ``same_name``: among what is left, the *normalised* names are equal (case, accents,
   punctuation and a leading ``"123 - "`` number are ignored) and the stations are within
   ``name_radius_m``.
3. ``nearest``: among what is left, the stations within ``radius_m``, closest first.

What remains is reported as ``none`` (in the old table only: the station disappeared) or
``only_new`` (in the new table only: it appeared). Matching is done system by system, so two
systems that reuse the same numbers never match each other. The result is deterministic: ties are
broken by distance and then by identifier.

Examples
--------
>>> import pandas as pd
>>> from gbfs_toolkit.stations.match import match_stations
>>> old = pd.DataFrame({"station_id": ["1", "2", "3"],
...                     "name": ["Gare", "Mairie", "Port"],
...                     "lat": [43.600, 43.610, 43.620], "lon": [3.88, 3.88, 3.88]})
>>> new = pd.DataFrame({"station_id": ["1", "20", "99"],
...                     "name": ["Gare", "MAIRIE", "Stade"],
...                     "lat": [43.600, 43.6101, 43.700], "lon": [3.88, 3.88, 3.88]})
>>> m = match_stations(old, new)
>>> m["match_method"].tolist()
['same_id', 'same_name', 'none', 'only_new']
>>> m["station_id_old"].fillna("-").tolist(), m["station_id_new"].fillna("-").tolist()
(['1', '2', '3', '-'], ['1', '20', '-', '99'])
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

from gbfs_toolkit.core._common import need_columns
from gbfs_toolkit.spatial.geometry import GeoKDTree, haversine_m

__all__ = [
    "MATCH_COLUMNS",
    "METHODS",
    "normalize_station_name",
    "match_stations",
    "id_continuity",
]

_log = logging.getLogger(__name__)

#: Output columns of :func:`match_stations`.
MATCH_COLUMNS: list[str] = [
    "system_id",
    "station_id_old",
    "station_id_new",
    "match_method",
    "distance_m",
    "name_old",
    "name_new",
]
#: The values of ``match_method``.
METHODS: tuple[str, ...] = ("same_id", "same_id_far", "same_name", "nearest", "none", "only_new")


def normalize_station_name(name: Any) -> str:
    """A name reduced to what identifies it: ASCII, upper case, letters and digits only.

    A leading station number (``"042 - "``, ``"12: "``) is dropped, because operators add and
    remove it.

    Examples
    --------
    >>> normalize_station_name("042 - Place de l'Europe") == normalize_station_name("PLACE DE L EUROPE")
    True
    >>> normalize_station_name("42 - Hôtel de Ville"), normalize_station_name(None)
    ('HOTELDEVILLE', '')
    """
    if name is None or (isinstance(name, float) and name != name) or name is pd.NA:
        return ""
    text = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode().upper()
    text = re.sub(r"^\s*\d+\s*[-–:]\s*", "", text)
    return re.sub(r"[^A-Z0-9]", "", text)


def _prepare(df: pd.DataFrame, what: str) -> pd.DataFrame:
    need_columns(df, ["station_id"], what=what)
    out = pd.DataFrame(
        {
            "system_id": df["system_id"].astype(str) if "system_id" in df.columns else "",
            "station_id": df["station_id"].astype(str),
            "name": df["name"].astype("object") if "name" in df.columns else None,
            "lat": pd.to_numeric(df["lat"], errors="coerce") if "lat" in df.columns else np.nan,
            "lon": pd.to_numeric(df["lon"], errors="coerce") if "lon" in df.columns else np.nan,
        }
    )
    out["norm"] = [normalize_station_name(n) for n in out["name"]]
    # An identifier repeated in one table keeps its last row (the latest description).
    return out.drop_duplicates(["system_id", "station_id"], keep="last").reset_index(drop=True)


def _match_system(
    old: pd.DataFrame,
    new: pd.DataFrame,
    same_id_far_m: float,
    name_radius_m: float,
    radius_m: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    taken_old: set[int] = set()
    taken_new: set[int] = set()
    new_by_id = {sid: i for i, sid in enumerate(new["station_id"])}

    def dist(i: int, j: int) -> float:
        a, b = old.iloc[i], new.iloc[j]
        if not np.isfinite([a["lat"], a["lon"], b["lat"], b["lon"]]).all():
            return float("nan")
        return float(haversine_m(a["lat"], a["lon"], b["lat"], b["lon"]))

    def pair(i: int, j: int, method: str, d: float) -> None:
        taken_old.add(i)
        taken_new.add(j)
        rows.append(
            {
                "station_id_old": old.at[i, "station_id"],
                "station_id_new": new.at[j, "station_id"],
                "match_method": method,
                "distance_m": d,
                "name_old": old.at[i, "name"],
                "name_new": new.at[j, "name"],
            }
        )

    for i, sid in enumerate(old["station_id"]):
        j = new_by_id.get(sid)
        if j is not None:
            d = dist(i, j)
            pair(i, j, "same_id_far" if d > same_id_far_m else "same_id", d)

    left_old = [i for i in range(len(old)) if i not in taken_old]
    left_new = [j for j in range(len(new)) if j not in taken_new]
    if left_old and left_new:
        sub_new = new.iloc[left_new]
        tree = GeoKDTree(sub_new["lat"].to_numpy(), sub_new["lon"].to_numpy())
        reach = max(radius_m, name_radius_m)
        hits = tree.query_radius(
            old.iloc[left_old]["lat"].to_numpy(), old.iloc[left_old]["lon"].to_numpy(), reach
        )
        candidates = []
        for i, found in zip(left_old, hits, strict=True):
            for k in found:
                j = left_new[int(k)]
                d = dist(i, j)
                named = bool(old.at[i, "norm"]) and old.at[i, "norm"] == new.at[j, "norm"]
                if (named and d <= name_radius_m) or d <= radius_m:
                    candidates.append(
                        (
                            0 if named else 1,
                            d,
                            old.at[i, "station_id"],
                            new.at[j, "station_id"],
                            i,
                            j,
                            named,
                        )
                    )
        for _, d, _, _, i, j, named in sorted(candidates, key=lambda c: c[:4]):
            if i in taken_old or j in taken_new:
                continue
            pair(i, j, "same_name" if named else "nearest", d)

    for i in range(len(old)):
        if i not in taken_old:
            rows.append(
                {
                    "station_id_old": old.at[i, "station_id"],
                    "station_id_new": None,
                    "match_method": "none",
                    "distance_m": np.nan,
                    "name_old": old.at[i, "name"],
                    "name_new": None,
                }
            )
    for j in range(len(new)):
        if j not in taken_new:
            rows.append(
                {
                    "station_id_old": None,
                    "station_id_new": new.at[j, "station_id"],
                    "match_method": "only_new",
                    "distance_m": np.nan,
                    "name_old": None,
                    "name_new": new.at[j, "name"],
                }
            )
    return rows


def match_stations(
    old: pd.DataFrame,
    new: pd.DataFrame,
    *,
    same_id_far_m: float = 300.0,
    name_radius_m: float = 150.0,
    radius_m: float = 100.0,
) -> pd.DataFrame:
    """Pair the stations of ``old`` with those of ``new``, one to one (see the module).

    Parameters
    ----------
    old, new : pandas.DataFrame
        ``station_id``; ``system_id`` (optional, matches are made within a system);
        ``name``, ``lat``, ``lon`` (optional: without coordinates only identical ids match).
    same_id_far_m : float, default 300
        Distance beyond which an identical id is labelled ``same_id_far``.
    name_radius_m : float, default 150
        Largest distance between two stations whose normalised names are equal.
    radius_m : float, default 100
        Largest distance between two stations matched on position alone.

    Returns
    -------
    pandas.DataFrame
        :data:`MATCH_COLUMNS`, one row per old station, per new station, or per pair, sorted
        by system then identifier. Ids are text, so a leading zero survives.

    Examples
    --------
    >>> import pandas as pd
    >>> a = pd.DataFrame({"station_id": ["a"], "lat": [43.0], "lon": [3.0]})
    >>> b = pd.DataFrame({"station_id": ["z"], "lat": [43.0005], "lon": [3.0]})
    >>> row = match_stations(a, b).iloc[0]
    >>> row["match_method"], round(float(row["distance_m"]))
    ('nearest', 56)
    """
    for name, value in (
        ("same_id_far_m", same_id_far_m),
        ("name_radius_m", name_radius_m),
        ("radius_m", radius_m),
    ):
        if value < 0:
            raise ValueError(f"{name} must not be negative")
    a, b = _prepare(old, "match_stations(old)"), _prepare(new, "match_stations(new)")
    rows: list[dict[str, Any]] = []
    for system in sorted(set(a["system_id"]) | set(b["system_id"])):
        sub = _match_system(
            a[a["system_id"] == system].reset_index(drop=True),
            b[b["system_id"] == system].reset_index(drop=True),
            same_id_far_m,
            name_radius_m,
            radius_m,
        )
        rows += [{"system_id": system, **r} for r in sub]
    out = pd.DataFrame(rows, columns=MATCH_COLUMNS)
    for c in ("station_id_old", "station_id_new", "name_old", "name_new"):
        out[c] = out[c].astype("string")
    order = {m: k for k, m in enumerate(METHODS)}
    out = out.assign(
        _m=out["match_method"].map(order),
        _k=out["station_id_old"].fillna(out["station_id_new"]),
    ).sort_values(["system_id", "_m", "_k"], kind="stable")
    if "system_id" not in old.columns and "system_id" not in new.columns:
        out["system_id"] = None
    _log.info("matched %s", out["match_method"].value_counts().to_dict())
    return out.drop(columns=["_m", "_k"]).reset_index(drop=True)


def id_continuity(periods: Mapping[str, pd.DataFrame], **options: float) -> pd.DataFrame:
    """How much of the station numbering survives from each period to the next.

    ``periods`` maps a label to the station table of that period, in chronological order
    (a ``dict`` keeps it). For each consecutive pair and each system the result counts the
    stations kept under the same id, found under another id or place, lost and appeared, and
    the median distance moved by those that matched. ``options`` go to :func:`match_stations`.

    Returns
    -------
    pandas.DataFrame
        ``from_period, to_period, system_id, n_old, n_new, n_same_id, n_matched_other, n_lost,
        n_new_only, share_same_id, median_distance_m``.

    Examples
    --------
    >>> import pandas as pd
    >>> t1 = pd.DataFrame({"station_id": ["a", "b"]})
    >>> t2 = pd.DataFrame({"station_id": ["a", "c"]})
    >>> r = id_continuity({"2025": t1, "2026": t2}).iloc[0]
    >>> int(r["n_same_id"]), int(r["n_lost"]), float(r["share_same_id"])
    (1, 1, 0.5)
    """
    labels = list(periods)
    rows = []
    for left, right in zip(labels[:-1], labels[1:], strict=True):
        m = match_stations(periods[left], periods[right], **options)
        for system, g in m.groupby("system_id", dropna=False, sort=True):
            method = g["match_method"]
            n_old = int(g["station_id_old"].notna().sum())
            same = int(method.isin(["same_id", "same_id_far"]).sum())
            matched = g[g["station_id_old"].notna() & g["station_id_new"].notna()]
            rows.append(
                {
                    "from_period": left,
                    "to_period": right,
                    "system_id": system,
                    "n_old": n_old,
                    "n_new": int(g["station_id_new"].notna().sum()),
                    "n_same_id": same,
                    "n_matched_other": int(method.isin(["same_name", "nearest"]).sum()),
                    "n_lost": int((method == "none").sum()),
                    "n_new_only": int((method == "only_new").sum()),
                    "share_same_id": same / n_old if n_old else float("nan"),
                    "median_distance_m": float(matched["distance_m"].median())
                    if len(matched)
                    else float("nan"),
                }
            )
    return pd.DataFrame(
        rows,
        columns=[
            "from_period",
            "to_period",
            "system_id",
            "n_old",
            "n_new",
            "n_same_id",
            "n_matched_other",
            "n_lost",
            "n_new_only",
            "share_same_id",
            "median_distance_m",
        ],
    )

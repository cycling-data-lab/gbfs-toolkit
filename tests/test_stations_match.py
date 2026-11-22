"""stations.match: one-to-one continuity of station identifiers."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from gbfs_toolkit.core.models import SchemaError
from gbfs_toolkit.stations.match import (
    MATCH_COLUMNS,
    id_continuity,
    match_stations,
    normalize_station_name,
)


def tbl(rows, system=None):
    df = pd.DataFrame(rows, columns=["station_id", "name", "lat", "lon"])
    if system is not None:
        df.insert(0, "system_id", system)
    return df


def methods(m):
    return {(r.station_id_old, r.station_id_new): r.match_method for r in m.itertuples()}


def test_normalised_names():
    assert normalize_station_name("042 - Hôtel de Ville") == normalize_station_name(
        "HOTEL  DE-VILLE"
    )
    assert normalize_station_name("12: Gare") == "GARE"
    assert normalize_station_name("") == "" == normalize_station_name(float("nan"))
    assert normalize_station_name(pd.NA) == ""


def test_every_rule_and_the_leftovers():
    old = tbl(
        [
            ("1", "Gare", 43.6, 3.88),
            ("2", "Mairie", 43.61, 3.88),
            ("3", "Port", 43.62, 3.88),
            ("4", "Parc", 43.63, 3.88),
            ("5", "Lycée", 43.64, 3.88),
        ]
    )
    new = tbl(
        [
            ("1", "Gare", 43.6, 3.88),  # same id
            ("20", "MAIRIE", 43.6104, 3.88),  # same name, 44 m
            ("40", "Jardin", 43.6301, 3.88),  # nearest, 11 m
            ("77", "Elsewhere", 43.9, 3.88),
        ]
    )  # appeared
    got = {
        (a if isinstance(a, str) else None, b if isinstance(b, str) else None): k
        for (a, b), k in methods(match_stations(old, new)).items()
    }
    assert got == {
        ("1", "1"): "same_id",
        ("2", "20"): "same_name",
        ("4", "40"): "nearest",
        ("3", None): "none",
        ("5", None): "none",
        (None, "77"): "only_new",
    }
    m = match_stations(old, new)
    assert (
        m["match_method"].tolist().count("none") == 2 and "only_new" in m["match_method"].tolist()
    )
    assert list(m.columns) == MATCH_COLUMNS
    row = m[m["station_id_old"] == "4"].iloc[0]
    assert (
        row["station_id_new"] == "40"
        and row["match_method"] == "nearest"
        and row["distance_m"] == pytest.approx(11, abs=1)
    )


def test_same_id_far_is_flagged_not_trusted():
    old, new = tbl([("1", "A", 43.0, 3.0)]), tbl([("1", "A", 43.1, 3.0)])
    m = match_stations(old, new)
    assert m["match_method"].tolist() == ["same_id_far"] and m["distance_m"].iloc[0] > 10_000
    assert match_stations(old, new, same_id_far_m=20_000)["match_method"].tolist() == ["same_id"]


def test_same_name_needs_to_be_close_and_nearest_is_the_closest():
    old = tbl([("a", "Gare", 43.0, 3.0)])
    far_same_name = tbl([("x", "gare", 43.01, 3.0)])  # 1.1 km
    assert match_stations(old, far_same_name)["match_method"].tolist() == ["none", "only_new"]
    two = tbl([("p", "Foo", 43.0007, 3.0), ("q", "Bar", 43.0003, 3.0)])  # 78 m and 33 m
    m = match_stations(old, two)
    assert (m["station_id_old"] == "a").sum() == 1
    assert m.loc[m["station_id_old"] == "a", "station_id_new"].iloc[0] == "q"


def test_a_named_pair_wins_over_a_closer_stranger():
    old = tbl([("a", "Gare", 43.0, 3.0)])
    new = tbl(
        [("p", "Other", 43.0002, 3.0), ("q", "GARE", 43.0010, 3.0)]
    )  # 22 m stranger, 111 m namesake
    m = match_stations(old, new)
    assert m.loc[m["station_id_old"] == "a", "station_id_new"].iloc[0] == "q"


def test_matching_is_one_to_one():
    old = tbl([("a", None, 43.0, 3.0), ("b", None, 43.00005, 3.0)])
    new = tbl([("x", None, 43.00002, 3.0)])
    m = match_stations(old, new)
    paired = m.dropna(subset=["station_id_old", "station_id_new"])
    assert len(paired) == 1 and paired["station_id_new"].is_unique


def test_systems_do_not_match_each_other():
    old = tbl([("1", "A", 43.0, 3.0)], system="x")
    new = tbl([("1", "A", 43.0, 3.0)], system="y")
    m = match_stations(old, new)
    assert sorted(m["match_method"]) == ["none", "only_new"] and sorted(m["system_id"]) == [
        "x",
        "y",
    ]


def test_no_coordinates_or_names_means_only_identical_ids():
    old = pd.DataFrame({"station_id": ["007", "8"]})
    new = pd.DataFrame({"station_id": ["007", "9"]})
    m = match_stations(old, new)
    assert m["match_method"].tolist() == ["same_id", "none", "only_new"]
    assert m["station_id_old"].iloc[0] == "007"  # the leading zeros survive
    assert (
        match_stations(pd.DataFrame({"station_id": []}), new)["match_method"].tolist()
        == ["only_new"] * 2
    )


def test_duplicated_ids_and_missing_coordinates_are_tolerated():
    old = tbl([("a", "X", 43.0, 3.0), ("a", "X2", 43.0, 3.0), ("b", "Y", np.nan, np.nan)])
    new = tbl([("a", "X", 43.0, 3.0), ("c", "Y", 43.0, 3.0)])
    m = match_stations(old, new)
    assert (
        len(m[m["station_id_old"] == "a"]) == 1
        and m.loc[m["station_id_old"] == "a", "name_old"].iloc[0] == "X2"
    )
    assert m.loc[m["station_id_old"] == "b", "match_method"].iloc[0] == "none"


def test_errors():
    with pytest.raises(SchemaError):
        match_stations(pd.DataFrame({"x": [1]}), tbl([]))
    with pytest.raises(ValueError):
        match_stations(tbl([]), tbl([]), radius_m=-1)


def test_id_continuity_summary():
    p1 = tbl([("a", "A", 43.0, 3.0), ("b", "B", 43.01, 3.0), ("c", "C", 43.02, 3.0)], system="s")
    p2 = tbl([("a", "A", 43.0, 3.0), ("bb", "B", 43.01, 3.0), ("d", "D", 43.5, 3.0)], system="s")
    p3 = tbl([("a", "A", 43.0, 3.0)], system="s")
    out = id_continuity({"2024": p1, "2025": p2, "2026": p3})
    first = out.iloc[0]
    assert (
        first["n_old"],
        first["n_new"],
        first["n_same_id"],
        first["n_matched_other"],
        first["n_lost"],
        first["n_new_only"],
    ) == (3, 3, 1, 1, 1, 1)
    assert first["share_same_id"] == pytest.approx(1 / 3)
    assert out["from_period"].tolist() == ["2024", "2025"] and out["to_period"].tolist() == [
        "2025",
        "2026",
    ]
    assert id_continuity({"only": p1}).empty


@settings(max_examples=40, deadline=None)
@given(n_old=st.integers(0, 12), n_new=st.integers(0, 12), seed=st.integers(0, 9999))
def test_property_one_to_one_and_every_station_accounted_for(n_old, n_new, seed):
    rng = np.random.default_rng(seed)

    def table(n, prefix):
        return pd.DataFrame(
            {
                "station_id": [
                    f"{prefix}{i % 7}" if rng.random() < 0.5 else f"{i}" for i in range(n)
                ],
                "name": [f"n{rng.integers(0, 5)}" for _ in range(n)],
                "lat": 43 + rng.random(n) * 0.003,
                "lon": 3 + rng.random(n) * 0.003,
            }
        )

    old, new = table(n_old, "o"), table(n_new, "n")
    m = match_stations(old, new)
    paired = m.dropna(subset=["station_id_old", "station_id_new"])
    assert paired["station_id_old"].is_unique and paired["station_id_new"].is_unique
    assert m["station_id_old"].dropna().nunique() == old["station_id"].nunique()
    assert m["station_id_new"].dropna().nunique() == new["station_id"].nunique()
    assert set(m["match_method"]) <= {
        "same_id",
        "same_id_far",
        "same_name",
        "nearest",
        "none",
        "only_new",
    }

"""audit_catalogue (batch fetch+audit) and inter-rater agreement helpers."""

import math

import numpy as np
import pandas as pd

import gbfs_toolkit as gb


class _FakeFeed:
    def __init__(self, info):
        self._info = info

    def station_information(self):
        return self._info


def _info(sid, station_type, capacity, n=20):
    return pd.DataFrame(
        {
            "system_id": sid,
            "station_id": [f"{sid}-{i}" for i in range(n)],
            "station_type": station_type,
            "capacity": capacity if isinstance(capacity, list) else [capacity] * n,
            "lat": 48.85 + 0.001 * np.arange(n),
            "lon": 2.35 + 0.001 * np.arange(n),
        }
    )


def test_audit_catalogue_fetches_audits_and_reports_status(monkeypatch):
    feeds = {
        "good": _FakeFeed(_info("good", "docked_bike", 20)),
        "ff": _FakeFeed(_info("ff", "free_floating", 0)),
        "dead": RuntimeError("boom"),
        "empty": _FakeFeed(pd.DataFrame(columns=["system_id"])),
    }
    monkeypatch.setattr("gbfs_toolkit.io.fetch.fetch_multiple", lambda ids, **kw: feeds)

    verdict, status = gb.audit_catalogue(["good", "ff", "dead", "empty"], a7_scope="all")
    assert status["good"].startswith("ok")
    assert status["dead"].startswith("unreachable")
    assert status["empty"] == "empty"
    # The free-floating system trips A3; the docked one does not.
    a3 = verdict.groupby("system_id")["A3"].max()
    assert a3["ff"] and not a3["good"]


def test_krippendorff_perfect_and_missing():
    assert gb.krippendorff_alpha([[1, 2, 3, 1], [1, 2, 3, 1]]) == 1.0
    a = gb.krippendorff_alpha([[1, 2, 3, 3, 2, 1, math.nan], [1, 2, 3, 3, 2, 2, 5]])
    assert 0.0 < a < 1.0  # high but imperfect agreement with a missing rating


def test_cohen_kappa_bounds():
    assert gb.cohen_kappa([1, 2, 3, 1], [1, 2, 3, 1]) == 1.0
    assert gb.cohen_kappa([1, 2, 1, 2], [2, 1, 2, 1]) < 0  # systematic disagreement


def test_wilson_interval_brackets_and_clamps():
    lo, hi = gb.wilson_interval(8, 10)
    assert 0 <= lo <= 0.8 <= hi <= 1
    assert gb.wilson_interval(0, 5)[0] == 0.0  # clamped at 0
    assert gb.wilson_interval(5, 5)[1] == 1.0  # clamped at 1

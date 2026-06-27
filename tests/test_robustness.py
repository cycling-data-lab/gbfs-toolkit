"""Tests for the v1.0-readiness batch: errors, regions/alerts, conditional GET,
catalog fallback, provenance (coverage_report / manifest), and an e2e round-trip."""

import pandas as pd
import pytest

from gbfs_toolkit import (
    GBFSError,
    GBFSFetchError,
    GBFSNotModified,
    SchemaError,
    audit_frames,
    build_availability_panel,
    calculate_net_flow,
    coverage_report,
    to_canonical_alerts,
    to_canonical_system_regions,
)

# --- exception hierarchy ----------------------------------------------------


def test_schema_error_is_gbfs_error_and_value_error():
    assert issubclass(SchemaError, GBFSError)
    assert issubclass(SchemaError, ValueError)


def test_fetch_error_is_gbfs_error():
    assert issubclass(GBFSFetchError, GBFSError)
    assert issubclass(GBFSNotModified, GBFSError)


# --- new canonical endpoints ------------------------------------------------


def test_system_regions_lookup():
    raw = {"data": {"regions": [{"region_id": "r1", "name": "Centre"}]}}
    df = to_canonical_system_regions(raw, system_id="x")
    assert df.iloc[0]["region_id"] == "r1"
    assert df.iloc[0]["name"] == "Centre"


def test_alerts_parsing_with_times():
    raw = {
        "data": {
            "alerts": [
                {
                    "alert_id": "a1",
                    "type": "SYSTEM_CLOSURE",
                    "summary": "Strike",
                    "times": [{"start": 1_700_000_000, "end": 1_700_086_400}],
                    "last_updated": 1_700_000_500,
                }
            ]
        }
    }
    df = to_canonical_alerts(raw, system_id="x")
    row = df.iloc[0]
    assert row["type"] == "SYSTEM_CLOSURE"
    assert str(row["start"].tz) == "UTC"
    assert row["start"] < row["end"]


# --- conditional GET --------------------------------------------------------


class _Resp:
    def __init__(self, status, payload=None, headers=None):
        self.status_code = status
        self._payload = payload or {}
        self.headers = headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError("http error")


class _FakeSession:
    """Returns 200 with an ETag first, then 304 when If-None-Match is sent."""

    def __init__(self):
        self.calls = 0

    def get(self, url, timeout=None, headers=None):
        self.calls += 1
        if headers and headers.get("If-None-Match") == 'W/"v1"':
            return _Resp(304)
        return _Resp(200, {"data": {"stations": []}}, {"ETag": 'W/"v1"'})


def test_conditional_get_raises_not_modified():
    from gbfs_toolkit import fetch_feed_json

    sess = _FakeSession()
    first = fetch_feed_json("u", session=sess)
    assert first.etag == 'W/"v1"'
    with pytest.raises(GBFSNotModified):
        fetch_feed_json("u", session=sess, etag=first.etag)


# --- catalog offline fallback -----------------------------------------------


def test_catalog_offline_fallback(tmp_path, monkeypatch):
    import gbfs_toolkit.catalog as cat

    cache = tmp_path / "systems.csv"
    cache.write_text("System ID,Name\nvelib,Velib\n", encoding="utf-8")
    monkeypatch.setattr(cat, "CACHE_PATH", cache)

    class _Boom:
        class RequestException(Exception):  # noqa: N818 — mirrors requests.RequestException
            pass

        def get(self, *a, **k):
            raise self.RequestException("down")

    # simulate `import requests` returning our boom module
    import sys

    boom = _Boom()
    monkeypatch.setitem(sys.modules, "requests", boom)
    with pytest.warns(UserWarning, match="cached copy"):
        df = cat.systems_catalog("https://example.invalid/offline.csv")
    assert "velib" in df["system_id"].tolist()


# --- provenance -------------------------------------------------------------


def test_coverage_report_uptime_and_gaps():
    # expected every 5 min over 15 min = 4 snapshots; station a has 4, station b has 2
    t = pd.to_datetime(
        ["2026-01-01T00:00Z", "2026-01-01T00:05Z", "2026-01-01T00:10Z", "2026-01-01T00:15Z"]
    )
    panel = pd.DataFrame(
        {
            "system_id": "x",
            "station_id": ["a", "a", "a", "a", "b", "b"],
            "fetched_at": list(t) + [t[0], t[3]],
        }
    )
    rep = coverage_report(panel, expected_freq="5min")
    assert rep.loc[("x", "a"), "uptime_pct"] == 100.0
    assert rep.loc[("x", "b"), "actual_snapshots"] == 2
    assert rep.loc[("x", "b"), "longest_gap_minutes"] == 15.0


def test_generate_manifest_hashes_partitions(tmp_path):
    pytest.importorskip("pyarrow")
    from gbfs_toolkit import append_to_parquet, generate_manifest

    base = tmp_path / "lake"
    snap = pd.DataFrame(
        {
            "system_id": "velib",
            "station_id": ["1"],
            "num_bikes_available": [5],
            "fetched_at": pd.to_datetime([1_700_000_000], unit="s", utc=True),
        }
    )
    append_to_parquet(snap, base)
    man = generate_manifest(base)
    assert man["n_files"] >= 1
    assert all(len(f["sha256"]) == 64 for f in man["files"])
    assert man["total_rows"] == 1
    assert "velib" in man.get("system_ids", [])


# --- end-to-end research pipeline ------------------------------------------


def _discovery():
    return {
        "version": "2.3",
        "data": {
            "en": {
                "feeds": [
                    {"name": "station_information", "url": "info"},
                    {"name": "station_status", "url": "status"},
                ]
            }
        },
    }


def test_e2e_raw_to_panel_to_stats(tmp_path):
    pytest.importorskip("pyarrow")
    from gbfs_toolkit import GBFSFeed, append_to_parquet

    info_raw = {
        "data": {"stations": [{"station_id": "1", "lat": 48.85, "lon": 2.35, "capacity": 10}]}
    }
    # two snapshots with changing availability
    base = tmp_path / "lake"
    for t, bikes in [(1_700_000_000, 6), (1_700_000_300, 2)]:
        status_raw = {
            "data": {
                "stations": [
                    {
                        "station_id": "1",
                        "num_bikes_available": bikes,
                        "num_docks_available": 10 - bikes,
                        "last_reported": t,
                    }
                ]
            }
        }
        docs = {"g": _discovery(), "info": info_raw, "status": status_raw}
        feed = GBFSFeed.from_url("g", get_json=docs.get, system_id="velib")
        status = feed.station_status()
        status["fetched_at"] = pd.to_datetime([t], unit="s", utc=True)[0]
        append_to_parquet(status, base)
        # audit_frames works on the same canonical frames (no feed needed)
        verdict = audit_frames(feed.station_information(), status, system_id="velib")
        assert set(verdict["audit_type"]) == {"static", "dynamic"}

    panel = build_availability_panel(base, system_id="velib")
    flow = calculate_net_flow(panel)
    assert flow[flow.station_id == "1"]["net_flow"].dropna().iloc[0] == -4.0
    rep = coverage_report(panel)
    assert rep.loc[("velib", "1"), "actual_snapshots"] == 2

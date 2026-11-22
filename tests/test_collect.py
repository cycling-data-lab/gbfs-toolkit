"""collect: politeness (User-Agent, ttl, back-off), typed missing values, day files, local server."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pandas as pd
import pytest

from gbfs_toolkit.collect import (
    FEED_KINDS,
    Collector,
    compact_collected,
    parse_station_status,
    parse_vehicle_status,
    read_collected,
)

pytest.importorskip("pyarrow")


# --- parsing ---------------------------------------------------------------------------


def test_missing_values_stay_missing_and_typed():
    doc = {
        "data": {
            "stations": [
                {
                    "station_id": 1,
                    "num_bikes_available": 3,
                    "num_docks_available": 2,
                    "is_renting": True,
                    "is_returning": False,
                    "last_reported": 1782900000,
                },
                {"station_id": 2},
                {
                    "station_id": 3,
                    "num_vehicles_available": 5,
                    "vehicle_docks_available": 1,
                    "is_renting": "false",
                },
                {"station_id": 4, "num_bikes_available": None, "is_renting": None},
            ]
        }
    }
    out = parse_station_status(doc, system_id="s", fetched_at=pd.Timestamp("2026-03-01T10:00Z"))
    assert out["num_bikes_available"].dtype == "Int64" and out["is_renting"].dtype == "boolean"
    assert out["num_bikes_available"].isna().tolist() == [False, True, False, True]
    assert out["num_docks_available"].isna().tolist() == [False, True, False, True]
    assert out["is_renting"].isna().tolist() == [False, True, False, True]
    assert out["is_renting"].iloc[2] is False or not out["is_renting"].iloc[2]
    assert out["is_returning"].isna().tolist() == [False, True, True, True]
    assert out["num_bikes_available"].iloc[2] == 5 and out["num_docks_available"].iloc[2] == 1
    assert out["last_reported"].isna().tolist() == [False, True, True, True]
    assert str(out["fetched_at"].dt.tz) == "UTC" and out["station_id"].tolist() == [
        "1",
        "2",
        "3",
        "4",
    ]
    # never a 0 nor a True invented for a station that published nothing
    nothing = out.loc[1]
    assert all(
        pd.isna(nothing[c]) for c in ("num_bikes_available", "num_docks_available", "is_renting")
    )


def test_missing_flags_are_not_defaulted_for_vehicles_either():
    doc = {"data": {"vehicles": [{"vehicle_id": "v", "lat": "43.6"}, {"foo": 1}, {"bike_id": 7}]}}
    out = parse_vehicle_status(doc, system_id="s")
    assert out["vehicle_id"].tolist() == ["v", "7"]
    assert out["is_disabled"].isna().all() and out["is_reserved"].isna().all()
    assert out["lat"].iloc[0] == 43.6 and pd.isna(out["lon"].iloc[0])


def test_parsers_survive_empty_and_odd_documents():
    assert parse_station_status({}, system_id="s").empty
    assert parse_station_status({"data": {"stations": []}}, system_id="s").shape[1] == 9
    assert parse_vehicle_status({"data": []}, system_id="s").empty
    junk = parse_station_status(
        {"data": {"stations": [{"station_id": "a", "num_bikes_available": "n/a"}]}}, system_id="s"
    )
    assert junk["num_bikes_available"].isna().all()


# --- the Collector against a fake in-process getter --------------------------------------

DISCOVERY = {
    "version": "2.3",
    "data": {
        "en": {
            "feeds": [
                {"name": "station_status", "url": "https://x/status.json"},
                {"name": "free_bike_status", "url": "https://x/bikes.json"},
            ]
        }
    },
}


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def make(tmp_path, docs, clock=None, **kw):
    clock = clock or Clock()
    calls = []

    def getter(url):
        calls.append(url)
        value = docs[url]
        if isinstance(value, Exception):
            raise value
        return value

    kw.setdefault("user_agent", "tests/1.0 (mailto:t@example.org)")
    c = Collector({"sys": "https://x/gbfs.json"}, tmp_path, get_json=getter, clock=clock, **kw)
    return c, calls, clock


def status_doc(n=2, ttl=30):
    return {
        "ttl": ttl,
        "data": {"stations": [{"station_id": str(i), "num_bikes_available": i} for i in range(n)]},
    }


def test_user_agent_is_required(tmp_path):
    for bad in ("", "   ", None):
        with pytest.raises(ValueError, match="user_agent"):
            Collector({"s": "https://x"}, tmp_path, user_agent=bad)  # type: ignore[arg-type]
    with pytest.raises(TypeError):  # no default either
        Collector({"s": "https://x"}, tmp_path)  # type: ignore[call-arg]


def test_argument_validation(tmp_path):
    with pytest.raises(ValueError):
        Collector({}, tmp_path, user_agent="ua")
    with pytest.raises(ValueError):
        Collector({"s": "u"}, tmp_path, user_agent="ua", feeds=("alerts",))
    with pytest.raises(ValueError):
        Collector(pd.DataFrame({"system_id": ["a"]}), tmp_path, user_agent="ua")
    c = Collector(
        pd.DataFrame({"system_id": ["a", "b"], "auto_discovery_url": ["u", None]}),
        tmp_path,
        user_agent="ua",
    )
    assert c.systems == {"a": "u"}


def test_ttl_is_respected_then_released(tmp_path):
    c, calls, clock = make(
        tmp_path, {"https://x/gbfs.json": DISCOVERY, "https://x/status.json": status_doc(ttl=30)}
    )
    assert c.poll_once()["outcome"].tolist() == ["collected"]
    clock.t += 10
    assert c.poll_once()["outcome"].tolist() == ["skipped_ttl"]
    assert calls.count("https://x/status.json") == 1
    clock.t += 25  # 35 s after the first poll, ttl 30
    assert c.poll_once()["outcome"].tolist() == ["collected"]
    assert calls.count("https://x/gbfs.json") == 1  # discovery is remembered
    assert len(read_collected(tmp_path)) == 4


def test_min_interval_applies_when_ttl_is_zero(tmp_path):
    c, _, clock = make(
        tmp_path,
        {"https://x/gbfs.json": DISCOVERY, "https://x/status.json": status_doc(ttl=0)},
        min_interval=5,
    )
    c.poll_once()
    clock.t += 2
    assert c.poll_once()["outcome"].tolist() == ["skipped_ttl"]
    clock.t += 4
    assert c.poll_once()["outcome"].tolist() == ["collected"]


def test_ttl_can_be_ignored_on_purpose(tmp_path):
    c, _, clock = make(
        tmp_path,
        {"https://x/gbfs.json": DISCOVERY, "https://x/status.json": status_doc(ttl=600)},
        respect_ttl=False,
        min_interval=0,
    )
    c.poll_once()
    assert c.poll_once()["outcome"].tolist() == ["collected"]


def test_failures_back_off_exponentially_then_recover(tmp_path):
    from gbfs_toolkit.core.errors import GBFSFetchError

    docs = {"https://x/gbfs.json": DISCOVERY, "https://x/status.json": GBFSFetchError("boom")}
    c, calls, clock = make(tmp_path, docs, min_interval=1, max_backoff=100)
    first = c.poll_once()
    assert first["outcome"].tolist() == ["failed"] and "boom" in first["error"].iloc[0]
    clock.t += 1
    assert c.poll_once()["outcome"].tolist() == ["skipped_backoff"]  # waits 2 s
    clock.t += 2
    assert c.poll_once()["outcome"].tolist() == ["failed"]  # 2nd failure: waits 4 s
    clock.t += 3
    assert c.poll_once()["outcome"].tolist() == ["skipped_backoff"]
    docs["https://x/status.json"] = status_doc(ttl=0)
    clock.t += 2
    assert c.poll_once()["outcome"].tolist() == ["collected"]
    assert c._state[("sys", "station_status")].failures == 0


def test_backoff_is_capped(tmp_path):
    from gbfs_toolkit.core.errors import GBFSFetchError

    docs = {"https://x/gbfs.json": DISCOVERY, "https://x/status.json": GBFSFetchError("boom")}
    c, _, clock = make(tmp_path, docs, min_interval=1, max_backoff=10)
    for _ in range(8):
        c.poll_once()
        clock.t += 11
    assert (
        c._state[("sys", "station_status")].next_at - clock.t <= 0
    )  # always retried within the cap


def test_a_failing_system_does_not_stop_the_others(tmp_path):
    docs = {
        "https://x/gbfs.json": DISCOVERY,
        "https://x/status.json": status_doc(),
        "https://y/gbfs.json": ValueError("not json"),
    }
    c = Collector(
        {"good": "https://x/gbfs.json", "bad": "https://y/gbfs.json"},
        tmp_path,
        user_agent="ua",
        get_json=lambda u: _lookup(docs, u),
        min_interval=0,
    )
    out = c.poll_once().set_index("system_id")["outcome"].to_dict()
    assert out == {"good": "collected", "bad": "failed"}


def _lookup(docs, url):
    v = docs[url]
    if isinstance(v, Exception):
        raise v
    return v


def test_feed_that_the_system_does_not_publish(tmp_path):
    only_status = {
        "version": "2.3",
        "data": {"en": {"feeds": [{"name": "station_status", "url": "https://x/status.json"}]}},
    }
    c, calls, clock = make(
        tmp_path,
        {"https://x/gbfs.json": only_status, "https://x/status.json": status_doc()},
        feeds=("station_status", "vehicle_status"),
    )
    out = c.poll_once().set_index("feed")["outcome"].to_dict()
    assert out == {"station_status": "collected", "vehicle_status": "unavailable"}
    clock.t += 100
    assert (
        c.poll_once().set_index("feed")["outcome"]["vehicle_status"] == "unavailable"
    )  # not re-discovered every poll
    assert calls.count("https://x/gbfs.json") == 2  # once per feed kind, at the first poll


def test_vehicle_feeds_v2_and_v3(tmp_path):
    v3 = {
        "version": "3.0",
        "data": {"feeds": [{"name": "vehicle_status", "url": "https://x/v.json"}]},
    }
    docs = {
        "https://x/gbfs.json": v3,
        "https://x/v.json": {
            "ttl": 0,
            "data": {"vehicles": [{"vehicle_id": "a", "lat": 1, "lon": 2}]},
        },
    }
    c, _, _ = make(tmp_path, docs, feeds=("vehicle_status",), min_interval=0)
    assert c.poll_once()["rows"].tolist() == [1]
    assert read_collected(tmp_path, "vehicle_status")["vehicle_id"].tolist() == ["a"]
    assert "free_bike_status" not in FEED_KINDS


def test_empty_feed_is_reported_not_written(tmp_path):
    c, _, _ = make(
        tmp_path,
        {
            "https://x/gbfs.json": DISCOVERY,
            "https://x/status.json": {"ttl": 0, "data": {"stations": []}},
        },
    )
    assert c.poll_once()["outcome"].tolist() == ["empty"]
    assert read_collected(tmp_path).empty


def test_day_files_split_by_utc_day_and_keep_types(tmp_path):
    clock = Clock()
    docs = {
        "https://x/gbfs.json": DISCOVERY,
        "https://x/status.json": {"ttl": 0, "data": {"stations": [{"station_id": "a"}]}},
    }
    times = iter(
        pd.to_datetime(["2026-03-01T23:59:00Z", "2026-03-01T23:59:30Z", "2026-03-02T00:00:10Z"])
    )
    c, _, _ = make(
        tmp_path, docs, clock=clock, min_interval=0, now=lambda: next(times), write="day"
    )
    for _ in range(3):
        c.poll_once()
    assert sorted(p.name for p in (tmp_path / "station_status" / "sys").glob("*.parquet")) == [
        "2026-03-01.parquet",
        "2026-03-02.parquet",
    ]
    day1 = pd.read_parquet(tmp_path / "station_status" / "sys" / "2026-03-01.parquet")
    assert (
        len(day1) == 2
        and day1["num_bikes_available"].dtype == "Int64"
        and day1["is_renting"].dtype == "boolean"
    )
    assert day1["num_bikes_available"].isna().all()  # stored empty, not 0
    window = read_collected(tmp_path, start="2026-03-02", end="2026-03-02")
    assert len(window) == 1
    assert len(read_collected(tmp_path, systems=["nobody"])) == 0
    assert not list(tmp_path.rglob("*.tmp"))


def test_unreadable_day_file_is_skipped_or_raised(tmp_path, caplog):
    c, _, _ = make(
        tmp_path,
        {"https://x/gbfs.json": DISCOVERY, "https://x/status.json": status_doc(ttl=0)},
        min_interval=0,
        write="day",
    )
    c.poll_once()
    good = next((tmp_path / "station_status" / "sys").glob("*.parquet"))
    (good.parent / "2020-01-01.parquet").write_bytes(b"PAR1 truncated")
    with caplog.at_level("WARNING", logger="gbfs_toolkit"):
        assert len(read_collected(tmp_path)) == 2
    assert "unreadable" in caplog.text
    with pytest.raises((OSError, ValueError)):
        read_collected(tmp_path, on_error="raise")
    with pytest.raises(ValueError):
        read_collected(tmp_path, "alerts")


def test_run_is_bounded_and_sleeps_between_polls(tmp_path):
    docs = {"https://x/gbfs.json": DISCOVERY, "https://x/status.json": status_doc(ttl=0)}
    c, _, clock = make(tmp_path, docs, min_interval=0)
    pauses = []
    summary = c.run(interval=60, max_iterations=3, sleep=lambda s: pauses.append(s))
    assert summary == {"iterations": 3, "rows": 6, "outcomes": {"collected": 3}}
    assert pauses == [60, 60]
    seen = []
    c2, _, clock2 = make(tmp_path / "b", docs, min_interval=0)
    c2.run(
        interval=10,
        duration=25,
        sleep=lambda s: setattr(clock2, "t", clock2.t + s),
        on_poll=lambda i, r: seen.append(i),
    )
    assert seen == [1, 2, 3]
    with pytest.raises(ValueError):
        c.run(interval=0)


def test_run_stops_cleanly_on_ctrl_c(tmp_path):
    docs = {"https://x/gbfs.json": DISCOVERY, "https://x/status.json": status_doc(ttl=0)}
    c, _, _ = make(tmp_path, docs, min_interval=0)

    def interrupt(_):
        raise KeyboardInterrupt

    assert c.run(interval=1, sleep=interrupt)["iterations"] == 1


# --- against a real local HTTP server (loopback is allowed offline) ------------------------


class Fake:
    """A tiny GBFS server: documents, a request log and scripted failures."""

    def __init__(self):
        self.requests: list[dict] = []
        self.responses: dict[str, list] = {}
        self.etags: dict[str, str] = {}
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                outer.requests.append(
                    {
                        "path": self.path,
                        "ua": self.headers.get("User-Agent"),
                        "inm": self.headers.get("If-None-Match"),
                    }
                )
                queue = outer.responses.get(self.path)
                if queue is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                item = queue.pop(0) if len(queue) > 1 else queue[0]
                status, body, headers = item
                if (
                    outer.etags.get(self.path)
                    and self.headers.get("If-None-Match") == outer.etags[self.path]
                ):
                    self.send_response(304)
                    self.end_headers()
                    return
                payload = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                for k, v in headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def fake():
    pytest.importorskip("requests")
    f = Fake()
    f.responses["/gbfs.json"] = [
        (
            200,
            {
                "version": "2.3",
                "data": {
                    "en": {"feeds": [{"name": "station_status", "url": f.url + "/status.json"}]}
                },
            },
            {},
        )
    ]
    yield f
    f.close()


def test_http_sends_our_user_agent_and_writes_rows(fake, tmp_path):
    fake.responses["/status.json"] = [(200, status_doc(3, ttl=0), {})]
    c = Collector(
        {"s": fake.url + "/gbfs.json"},
        tmp_path,
        user_agent="lab-test/2.0 (mailto:a@b.org)",
        min_interval=0,
    )
    assert c.poll_once()["rows"].tolist() == [3]
    assert {r["ua"] for r in fake.requests} == {"lab-test/2.0 (mailto:a@b.org)"}
    assert len(read_collected(tmp_path)) == 3


def test_http_retries_a_transient_503_and_honours_the_attempt_budget(fake, tmp_path):
    fake.responses["/status.json"] = [
        (503, {"error": "busy"}, {"Retry-After": "0"}),
        (200, status_doc(1, ttl=0), {}),
    ]
    c = Collector(
        {"s": fake.url + "/gbfs.json"},
        tmp_path,
        user_agent="ua",
        min_interval=0,
        retries=2,
        backoff_factor=0.01,
    )
    assert c.poll_once()["outcome"].tolist() == ["collected"]
    assert [r["path"] for r in fake.requests].count("/status.json") == 2


def test_http_error_and_bad_json_are_failures_not_exceptions(fake, tmp_path):
    fake.responses["/status.json"] = [(200, b"<html>not json</html>", {})]
    c = Collector({"s": fake.url + "/gbfs.json"}, tmp_path, user_agent="ua", min_interval=0)
    out = c.poll_once()
    assert out["outcome"].tolist() == ["failed"] and "failed to fetch" in out["error"].iloc[0]
    unknown = Collector({"s": fake.url + "/missing.json"}, tmp_path, user_agent="ua")
    assert unknown.poll_once()["outcome"].tolist() == ["failed"]


def test_http_conditional_requests_use_the_etag(fake, tmp_path):
    fake.responses["/status.json"] = [(200, status_doc(1, ttl=0), {"ETag": '"v1"'})]
    fake.etags["/status.json"] = '"v1"'
    c = Collector({"s": fake.url + "/gbfs.json"}, tmp_path, user_agent="ua", min_interval=0)
    assert c.poll_once()["outcome"].tolist() == ["collected"]
    assert c.poll_once()["outcome"].tolist() == ["skipped_ttl"]  # 304: nothing new to store
    assert fake.requests[-1]["inm"] == '"v1"'
    assert len(read_collected(tmp_path)) == 1


@pytest.mark.network
def test_live_feed_smoke(tmp_path):  # skipped unless --run-network
    c = Collector(
        {"nextbike_paris": "https://gbfs.nextbike.net/maps/gbfs/v2/nextbike_fr/gbfs.json"},
        tmp_path,
        user_agent="gbfs-toolkit-tests (+https://github.com/cycling-data-lab/gbfs-toolkit)",
    )
    assert c.poll_once()["outcome"].tolist() in (["collected"], ["unavailable"])


# --- fragments and compaction --------------------------------------------------------------


def polls(tmp_path, instants, **kw):
    """A collector whose clock walks through ``instants``; polls once per instant."""
    docs = {"https://x/gbfs.json": DISCOVERY, "https://x/status.json": status_doc(ttl=0)}
    times = iter(pd.to_datetime(instants))
    c, _, _ = make(tmp_path, docs, min_interval=0, now=lambda: next(times), **kw)
    for _ in instants:
        c.poll_once()
    return c


def frag_files(tmp_path):
    return sorted((tmp_path / "station_status" / "sys" / "_fragments").rglob("*.parquet"))


def test_a_poll_writes_a_new_fragment_and_never_touches_the_earlier_ones(tmp_path):
    docs = {"https://x/gbfs.json": DISCOVERY, "https://x/status.json": status_doc(ttl=0)}
    times = iter(pd.to_datetime(["2026-03-01T10:00:00Z", "2026-03-01T10:01:00Z"]))
    c, _, _ = make(tmp_path, docs, min_interval=0, now=lambda: next(times))
    c.poll_once()
    first = frag_files(tmp_path)
    stamps = {f: f.stat().st_mtime_ns for f in first}
    c.poll_once()
    after = frag_files(tmp_path)
    assert len(first) == 1 and len(after) == 2 and set(first) <= set(after)
    assert all(f.stat().st_mtime_ns == stamps[f] for f in first)  # not rewritten
    assert not list((tmp_path / "station_status" / "sys").glob("*.parquet"))  # no day file yet
    assert len(read_collected(tmp_path)) == 4  # but it reads them all
    assert not list(tmp_path.rglob("*.tmp"))


def test_write_mode_is_validated(tmp_path):
    with pytest.raises(ValueError, match="write"):
        Collector({"s": "https://x"}, tmp_path, user_agent="t (mailto:t@x.org)", write="rows")


def test_compaction_gathers_closed_days_atomically_and_is_idempotent(tmp_path):
    instants = [
        "2026-03-01T23:58:00Z",
        "2026-03-01T23:59:00Z",
        "2026-03-02T00:01:00Z",
        "2026-03-02T00:02:00Z",
    ]
    polls(tmp_path, instants)
    before = read_collected(tmp_path)
    clock = lambda: pd.Timestamp("2026-03-02T12:00:00Z")  # noqa: E731
    done = compact_collected(tmp_path, now=clock)
    assert done[["system_id", "day", "fragments", "rows"]].values.tolist() == [
        ["sys", "2026-03-01", 2, 4]
    ]
    day = tmp_path / "station_status" / "sys" / "2026-03-01.parquet"
    assert day.exists() and len(frag_files(tmp_path)) == 2  # today's two are left alone
    assert read_collected(tmp_path).equals(before)  # nothing lost or invented
    stamp = day.stat().st_mtime_ns
    again = compact_collected(tmp_path, now=clock)
    assert again.empty and day.stat().st_mtime_ns == stamp  # idempotent: no rewrite
    done = compact_collected(tmp_path, now=clock, include_today=True)
    assert done["rows"].tolist() == [4] and not frag_files(tmp_path)
    assert not (tmp_path / "station_status" / "sys" / "_fragments").exists()
    assert read_collected(tmp_path).equals(before)
    assert not list(tmp_path.rglob("*.tmp"))
    types = pd.read_parquet(day)
    assert types["num_bikes_available"].dtype == "Int64" and types["is_renting"].dtype == "boolean"


def test_an_interrupted_compaction_loses_nothing_and_counts_nothing_twice(tmp_path):
    polls(tmp_path, ["2026-03-01T10:00:00Z", "2026-03-01T10:01:00Z"])
    before = read_collected(tmp_path)
    saved = {f: f.read_bytes() for f in frag_files(tmp_path)}
    clock = lambda: pd.Timestamp("2026-03-05T00:00:00Z")  # noqa: E731
    compact_collected(tmp_path, now=clock)
    for f, data in saved.items():  # as if the process died before removing the fragments
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(data)
    assert read_collected(tmp_path).equals(before)  # read: exact duplicates counted once
    done = compact_collected(tmp_path, now=clock)
    assert done["rows"].tolist() == [4]  # compaction: the day file, deduplicated
    assert read_collected(tmp_path).equals(before) and not frag_files(tmp_path)


def test_compaction_leaves_an_unreadable_fragment_and_a_late_fragment_alone(tmp_path, caplog):
    polls(tmp_path, ["2026-03-01T10:00:00Z", "2026-03-01T10:01:00Z"])
    bad = frag_files(tmp_path)[0].parent / "000000000000-bad.parquet"
    bad.write_bytes(b"PAR1 truncated")
    clock = lambda: pd.Timestamp("2026-03-05T00:00:00Z")  # noqa: E731
    with caplog.at_level("WARNING", logger="gbfs_toolkit"):
        done = compact_collected(tmp_path, now=clock)
    assert done["fragments"].tolist() == [2] and bad.exists()
    assert "unreadable" in caplog.text
    assert len(read_collected(tmp_path)) == 4


def test_compaction_options_and_an_empty_folder(tmp_path):
    assert compact_collected(tmp_path / "none").empty
    polls(tmp_path, ["2026-03-01T10:00:00Z"])
    clock = lambda: pd.Timestamp("2026-03-05T00:00:00Z")  # noqa: E731
    assert compact_collected(tmp_path, systems=["other"], now=clock).empty
    assert compact_collected(tmp_path, "vehicle_status", now=clock).empty
    with pytest.raises(ValueError, match="kind"):
        compact_collected(tmp_path, "alerts")
    c = polls(tmp_path / "second", ["2026-03-01T10:00:00Z"])
    assert len(c.compact(include_today=True, now=clock)) == 1


def test_collected_folder_is_a_path_source_for_quality_and_aggregate(tmp_path):
    pytest.importorskip("duckdb")
    from gbfs_toolkit.aggregate import aggregate_availability
    from gbfs_toolkit.quality import daily_coverage

    polls(tmp_path, ["2026-03-01T10:00:00Z", "2026-03-01T10:01:00Z", "2026-03-02T10:00:00Z"])
    compact_collected(tmp_path, now=lambda: pd.Timestamp("2026-03-02T12:00:00Z"))
    folder = tmp_path / "station_status"  # one day file and one fragment
    agg = aggregate_availability(folder, "1D", time_col="fetched_at")
    assert int(agg["n_obs"].sum()) == 6
    cov = daily_coverage(folder)
    assert cov["actual_polls"].tolist() == [2, 1]

"""The experimental CLI commands: collect, quality, release, verify."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pandas as pd
import pytest

from gbfs_toolkit.interfaces.cli import main

pytest.importorskip("pyarrow")


@pytest.fixture
def server():
    pytest.importorskip("requests")
    hits = []

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            hits.append((self.path, self.headers.get("User-Agent")))
            base = f"http://127.0.0.1:{self.server.server_address[1]}"
            if self.path == "/gbfs.json":
                doc = {
                    "version": "2.3",
                    "data": {
                        "en": {"feeds": [{"name": "station_status", "url": base + "/s.json"}]}
                    },
                }
            else:
                doc = {
                    "ttl": 0,
                    "data": {
                        "stations": [
                            {"station_id": "1", "num_bikes_available": 2},
                            {"station_id": "2"},
                        ]
                    },
                }
            body = json.dumps(doc).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", hits
    srv.shutdown()
    srv.server_close()


def test_help_lists_the_new_commands(capsys):
    with pytest.raises(SystemExit) as e:
        main(["--help"])
    assert e.value.code == 0
    text = capsys.readouterr().out
    for command in ("audit", "collect", "compact", "quality", "release", "verify"):
        assert command in text
    for command in ("collect", "compact", "quality", "release", "verify"):
        with pytest.raises(SystemExit):
            main([command, "--help"])
        assert "experimental" in capsys.readouterr().out.lower()


def test_collect_requires_a_user_agent(tmp_path, capsys):
    with pytest.raises(SystemExit) as e:
        main(["collect", "--system", "a=http://x", "--out", str(tmp_path)])
    assert e.value.code == 2 and "--user-agent" in capsys.readouterr().err
    assert main(["collect", "--out", str(tmp_path), "--user-agent", "ua"]) == 2  # no system
    assert (
        main(["collect", "--system", "broken", "--out", str(tmp_path), "--user-agent", "ua"]) == 2
    )


def test_collect_once_and_a_bounded_loop(server, tmp_path, capsys):
    url, hits = server
    rc = main(
        [
            "collect",
            "--system",
            f"demo={url}/gbfs.json",
            "--out",
            str(tmp_path / "c"),
            "--user-agent",
            "cli-test/1.0 (mailto:t@example.org)",
            "--min-interval",
            "0",
        ]
    )
    assert rc == 0 and "poll 1: 2 row(s)" in capsys.readouterr().out
    assert {ua for _, ua in hits} == {"cli-test/1.0 (mailto:t@example.org)"}
    rc = main(
        [
            "collect",
            "--system",
            f"demo={url}/gbfs.json",
            "--out",
            str(tmp_path / "c"),
            "--user-agent",
            "ua@x",
            "--interval",
            "0.01",
            "--iterations",
            "2",
            "--min-interval",
            "0",
        ]
    )
    assert rc == 0 and "done: 2 poll(s)" in capsys.readouterr().out
    from gbfs_toolkit.collect import read_collected

    assert len(read_collected(tmp_path / "c")) == 6


def test_collect_reports_a_failing_feed_with_exit_1(tmp_path, capsys):
    pytest.importorskip("requests")
    rc = main(
        [
            "collect",
            "--system",
            "dead=http://127.0.0.1:9/gbfs.json",
            "--out",
            str(tmp_path),
            "--user-agent",
            "ua@x",
        ]
    )
    assert rc == 1 and "dead station_status" in capsys.readouterr().err


def test_systems_file_csv_and_json(server, tmp_path, capsys):
    url, _ = server
    (tmp_path / "s.csv").write_text(f"system_id,gbfs_url\ndemo,{url}/gbfs.json\n")
    assert (
        main(
            [
                "collect",
                "--systems-file",
                str(tmp_path / "s.csv"),
                "--out",
                str(tmp_path / "o1"),
                "--user-agent",
                "ua@x",
                "--min-interval",
                "0",
            ]
        )
        == 0
    )
    (tmp_path / "s.json").write_text(json.dumps({"demo": f"{url}/gbfs.json"}))
    assert (
        main(
            [
                "collect",
                "--systems-file",
                str(tmp_path / "s.json"),
                "--out",
                str(tmp_path / "o2"),
                "--user-agent",
                "ua@x",
                "--min-interval",
                "0",
            ]
        )
        == 0
    )
    capsys.readouterr()


def make_lake(tmp_path):
    from gbfs_toolkit.store import write_lake

    t = pd.date_range("2026-03-01", periods=2 * 1440, freq="min", tz="UTC")
    df = pd.concat(
        [
            pd.DataFrame(
                {
                    "system_id": "a",
                    "station_id": "s",
                    "observed_at_utc": t,
                    "num_bikes_available": 3,
                    "num_docks_available": 2,
                }
            ),
            pd.DataFrame(
                {
                    "system_id": "b",
                    "station_id": "s",
                    "observed_at_utc": t[:1440],
                    "num_bikes_available": 3,
                    "num_docks_available": 2,
                }
            ),
        ]
    )
    write_lake(df, tmp_path / "lake")
    return tmp_path / "lake"


def test_quality_prints_a_table_writes_files_and_has_a_strict_mode(tmp_path, capsys):
    lake = make_lake(tmp_path)
    assert main(["quality", str(lake), "--out", str(tmp_path / "q")]) == 0
    out = capsys.readouterr().out
    assert "outage_operator" in out and "incident(s)" in out
    assert (tmp_path / "q" / "daily_coverage.csv").exists() and (
        tmp_path / "q" / "incidents.json"
    ).exists()
    assert main(["quality", str(lake), "--strict"]) == 1  # b is silent on day 2
    assert main(["quality", str(lake), "--strict", "--end", "2026-03-01"]) == 0
    capsys.readouterr()
    main(["quality", str(lake), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["days_by_status"]["outage_operator"] == 1
    assert main(["quality", str(tmp_path / "nothing")]) == 2


def test_quality_reads_the_collect_layout(server, tmp_path, capsys):
    url, _ = server
    main(
        [
            "collect",
            "--system",
            f"demo={url}/gbfs.json",
            "--out",
            str(tmp_path / "c"),
            "--user-agent",
            "ua@x",
            "--min-interval",
            "0",
        ]
    )
    capsys.readouterr()
    assert main(["quality", str(tmp_path / "c"), "--layout", "collected"]) == 0
    assert "demo" in capsys.readouterr().out


def test_collect_writes_fragments_and_compact_gathers_them(server, tmp_path, capsys):
    url, _ = server
    base = [
        "--system",
        f"demo={url}/gbfs.json",
        "--out",
        str(tmp_path / "c"),
        "--user-agent",
        "ua@x",
        "--min-interval",
        "0",
    ]
    assert main(["collect", *base]) == 0 and main(["collect", *base]) == 0
    folder = tmp_path / "c" / "station_status" / "demo"
    assert len(list(folder.rglob("*.parquet"))) == 2 and not list(folder.glob("*.parquet"))
    capsys.readouterr()
    assert main(["compact", str(tmp_path / "c")]) == 0
    assert "compacted 0 day file(s)" in capsys.readouterr().out  # today is still open
    assert main(["compact", str(tmp_path / "c"), "--include-today"]) == 0
    assert "compacted 1 day file(s) from 2 fragment(s)" in capsys.readouterr().out
    assert len(list(folder.glob("*.parquet"))) == 1
    # the day file and the fragments of a `--compact` run are the same data
    assert main(["collect", *base, "--compact"]) == 0
    assert main(["quality", str(tmp_path / "c"), "--layout", "collected"]) == 0


def test_collect_write_day_keeps_the_day_file(server, tmp_path):
    url, _ = server
    args = [
        "collect",
        "--system",
        f"demo={url}/gbfs.json",
        "--out",
        str(tmp_path / "d"),
        "--user-agent",
        "ua@x",
        "--min-interval",
        "0",
        "--write",
        "day",
    ]
    assert main(args) == 0
    assert len(list((tmp_path / "d" / "station_status" / "demo").glob("*.parquet"))) == 1


def test_release_then_verify_and_a_tampered_copy(tmp_path, capsys):
    lake = make_lake(tmp_path)
    rel = tmp_path / "rel"
    rc = main(
        [
            "release",
            str(lake),
            str(rel),
            "--name",
            "demo",
            "--start",
            "2026-03-01",
            "--end",
            "2026-03-02",
            "--license",
            "CC0-1.0",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0 and "nothing was uploaded" in out
    assert main(["verify", str(rel)]) == 0 and "OK" in capsys.readouterr().out
    assert main(["verify", str(rel), "--deep"]) == 0
    (rel / "README.md").write_text("changed")
    assert main(["verify", str(rel)]) == 1
    assert "mismatched: README.md" in capsys.readouterr().err
    assert (
        main(
            [
                "release",
                str(lake),
                str(rel),
                "--name",
                "x",
                "--start",
                "2026-03-01",
                "--end",
                "2026-03-02",
            ]
        )
        == 2
    )  # not empty
    assert (
        main(
            [
                "release",
                str(lake),
                str(tmp_path / "r2"),
                "--name",
                "x",
                "--start",
                "2026-03-01",
                "--end",
                "2099-01-01",
            ]
        )
        == 2
    )  # open period


def test_verify_a_manifest(tmp_path, capsys):
    from gbfs_toolkit.repro import create_manifest, write_manifest

    df = pd.DataFrame({"x": [1, 2, 3]})
    df.to_parquet(tmp_path / "t.parquet", index=False)
    mp = write_manifest(create_manifest(df, table="t"), tmp_path / "m.json")
    assert main(["verify", str(mp), "--data", str(tmp_path / "t.parquet")]) == 0
    pd.DataFrame({"x": [1, 2, 4]}).to_parquet(tmp_path / "u.parquet", index=False)
    assert main(["verify", str(mp), "--data", str(tmp_path / "u.parquet")]) == 1
    assert main(["verify", str(mp)]) == 2
    capsys.readouterr()

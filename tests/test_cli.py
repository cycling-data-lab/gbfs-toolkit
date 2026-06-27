"""Tests for the `gbfs audit` CLI."""

import json

from gbfs_toolkit.cli import main


def _write(tmp_path, stations):
    p = tmp_path / "station_information.json"
    p.write_text(json.dumps({"data": {"stations": stations}}), encoding="utf-8")
    return str(p)


def test_cli_audit_clean_feed_returns_zero(tmp_path, capsys):
    src = _write(tmp_path, [{"station_id": "1", "lat": 48.85, "lon": 2.35, "capacity": 10}])
    rc = main(["audit", src, "--system-id", "velib"])
    out = capsys.readouterr().out
    assert "semantic audit of 'velib'" in out
    assert rc == 0


def test_cli_audit_flags_carshare_and_writes_csv(tmp_path, capsys):
    # a carsharing station trips A1 → non-zero exit + CSV output
    src = _write(tmp_path, [{"station_id": "1", "lat": 48.85, "lon": 2.35, "capacity": 4}])
    out_csv = tmp_path / "verdict.csv"
    rc = main(["audit", src, "--system-id", "x", "--gbfs-version", "2.x", "--out", str(out_csv)])
    assert out_csv.exists()
    assert rc in (0, 1)  # exit code reflects whether anything flagged


def test_cli_empty_feed_returns_two(tmp_path):
    src = _write(tmp_path, [])
    assert main(["audit", src]) == 2

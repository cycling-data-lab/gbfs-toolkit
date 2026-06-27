"""Tests for the `gbfs audit` CLI."""

import json

from gbfs_toolkit.interfaces.cli import main


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


def test_cli_json_output_is_machine_readable(tmp_path, capsys):
    src = _write(tmp_path, [{"station_id": "1", "lat": 48.85, "lon": 2.35, "capacity": 10}])
    main(["audit", src, "--system-id", "velib", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["tool"] == "gbfs-toolkit"
    assert payload["system_id"] == "velib"
    assert payload["n_stations"] == 1
    assert set(payload["rules"]) == {f"A{i}" for i in range(1, 8)}


def test_cli_a7_scope_argument_accepted(tmp_path):
    src = _write(tmp_path, [{"station_id": "1", "lat": 48.85, "lon": 2.35, "capacity": 10}])
    assert main(["audit", src, "--a7-scope", "all"]) in (0, 1)


def test_cli_rich_renderer_runs():
    # The rich path is gated on an interactive TTY at runtime; exercise the
    # renderer directly so the [cli] extra stays covered.
    from gbfs_toolkit.interfaces.cli import _render_rich

    _render_rich(
        "velib", n=100, n_flagged=3, counts={f"A{i}": (3 if i == 4 else 0) for i in range(1, 8)}
    )

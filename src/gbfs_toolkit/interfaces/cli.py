"""Command-line interface: ``gbfs audit <station_information.json>``.

The semantic counterpart to MobilityData's syntactic ``gbfs-validator``.

Output adapts to context: a coloured table when ``rich`` is installed and the
output is an interactive terminal, plain text otherwise, or machine-readable
JSON with ``--json``. The core install needs none of this; ``rich`` lives behind
the ``[cli]`` extra (``pip install gbfs-toolkit[cli]``).
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

from gbfs_toolkit import __version__
from gbfs_toolkit.audit import audit_static
from gbfs_toolkit.core.errors import GBFSError
from gbfs_toolkit.core.models import AUDIT_FLAGS, RULES
from gbfs_toolkit.io.normalize import to_canonical_station_info


def _load(source: str) -> dict:
    if source.startswith(("http://", "https://")):
        with urllib.request.urlopen(source, timeout=30) as r:  # noqa: S310
            return json.load(r)
    with open(source, encoding="utf-8") as f:
        return json.load(f)


def _rule_counts(verdict) -> dict[str, int]:
    return {flag: int(verdict[flag].sum()) for flag in AUDIT_FLAGS}


def _use_rich(force_plain: bool) -> bool:
    """Use rich only when available and writing to an interactive terminal."""
    if force_plain:
        return False
    try:
        import rich  # noqa: F401
    except ImportError:
        return False
    return sys.stdout.isatty()


def _render_json(system_id: str, n: int, n_flagged: int, counts: dict[str, int]) -> None:
    payload = {
        "tool": "gbfs-toolkit",
        "version": __version__,
        "system_id": system_id,
        "n_stations": n,
        "n_flagged": n_flagged,
        "flagged_pct": round(100 * n_flagged / n, 2) if n else 0.0,
        "rules": counts,
    }
    print(json.dumps(payload, indent=2))


def _render_rich(system_id: str, n: int, n_flagged: int, counts: dict[str, int]) -> None:
    from rich.console import Console
    from rich.table import Table

    console = Console()
    pct = 100 * n_flagged / n if n else 0.0
    headline = "[bold green]clean[/]" if n_flagged == 0 else f"[bold red]{n_flagged} flagged[/]"
    console.print(
        f"[bold]gbfs-toolkit {__version__}[/] semantic audit of "
        f"[cyan]{system_id}[/]: {n} stations, {headline} ({pct:.1f}%)"
    )
    if n_flagged == 0:
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("Flag")
    table.add_column("Rule")
    table.add_column("Stations", justify="right")
    for flag in AUDIT_FLAGS:
        c = counts[flag]
        if c:
            colour = "red" if flag in ("A1", "A4", "A5") else "yellow"
            table.add_row(f"[{colour}]{flag}[/]", RULES[flag]["name"], str(c))
    console.print(table)


def _render_plain(system_id: str, n: int, n_flagged: int, counts: dict[str, int]) -> None:
    pct = 100 * n_flagged / n if n else 0.0
    print(f"gbfs-toolkit {__version__}: semantic audit of '{system_id}'")
    print(f"  stations: {n}   flagged: {n_flagged} ({pct:.1f}%)")
    for flag in AUDIT_FLAGS:
        c = counts[flag]
        if c:
            print(f"  {flag}  {RULES[flag]['name']:<26} {c} station(s)")


def _cmd_audit(args: argparse.Namespace) -> int:
    raw = _load(args.source)
    stations = to_canonical_station_info(
        raw, system_id=args.system_id, gbfs_version=args.gbfs_version
    )
    if stations.empty:
        print("No stations found in the feed.", file=sys.stderr)
        return 2
    verdict = audit_static(stations, a7_scope=args.a7_scope)
    n = len(verdict)
    n_flagged = int(verdict["flagged"].sum())
    counts = _rule_counts(verdict)

    if args.json:
        _render_json(args.system_id, n, n_flagged, counts)
    elif _use_rich(args.no_color):
        _render_rich(args.system_id, n, n_flagged, counts)
    else:
        _render_plain(args.system_id, n, n_flagged, counts)

    if args.out:
        verdict.to_csv(args.out, index=False)
        if not args.json:
            print(f"  verdict written to {args.out}")
    return 1 if n_flagged else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gbfs", description=__doc__)
    parser.add_argument("--version", action="version", version=f"gbfs-toolkit {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_audit = sub.add_parser("audit", help="semantic A1–A7 audit of a station_information feed")
    p_audit.add_argument("source", help="path or URL to station_information.json")
    p_audit.add_argument("--system-id", default="system", dest="system_id")
    p_audit.add_argument("--gbfs-version", default="2.x", dest="gbfs_version")
    p_audit.add_argument(
        "--a7-scope",
        choices=("docked", "all"),
        default="docked",
        dest="a7_scope",
        help="A7 null-capacity scope ('all' reproduces the gbfs-audit-catalogue verdicts)",
    )
    p_audit.add_argument("--out", help="write the per-station verdict to this CSV")
    p_audit.add_argument("--json", action="store_true", help="machine-readable JSON output")
    p_audit.add_argument("--no-color", action="store_true", help="force plain text (no rich)")
    p_audit.set_defaults(func=_cmd_audit)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except FileNotFoundError as e:
        print(f"gbfs: file not found: {e.filename}", file=sys.stderr)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        print(f"gbfs: could not parse JSON from {args.source!r}: {e}", file=sys.stderr)
    except urllib.error.URLError as e:
        print(f"gbfs: could not fetch {args.source!r}: {e.reason}", file=sys.stderr)
    except (GBFSError, OSError) as e:
        print(f"gbfs: {e}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

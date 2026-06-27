"""Command-line interface: ``gbfs audit <station_information.json>``.

The semantic counterpart to MobilityData's syntactic ``gbfs-validator``.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request

from gbfs_toolkit import __version__
from gbfs_toolkit.audit import audit_static
from gbfs_toolkit.models import AUDIT_FLAGS, RULES
from gbfs_toolkit.normalize import to_canonical_station_info


def _load(source: str) -> dict:
    if source.startswith(("http://", "https://")):
        with urllib.request.urlopen(source, timeout=30) as r:  # noqa: S310
            return json.load(r)
    with open(source, encoding="utf-8") as f:
        return json.load(f)


def _cmd_audit(args: argparse.Namespace) -> int:
    raw = _load(args.source)
    stations = to_canonical_station_info(
        raw, system_id=args.system_id, gbfs_version=args.gbfs_version
    )
    if stations.empty:
        print("No stations found in the feed.", file=sys.stderr)
        return 2
    verdict = audit_static(stations)
    n = len(verdict)
    n_flagged = int(verdict["flagged"].sum())
    print(f"gbfs-toolkit {__version__}: semantic audit of '{args.system_id}'")
    print(f"  stations: {n}   flagged: {n_flagged} ({100 * n_flagged / n:.1f}%)")
    for flag in AUDIT_FLAGS:
        c = int(verdict[flag].sum())
        if c:
            print(f"  {flag}  {RULES[flag]['name']:<26} {c} station(s)")
    if args.out:
        verdict.to_csv(args.out, index=False)
        print(f"  → verdict written to {args.out}")
    return 1 if n_flagged else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gbfs", description=__doc__)
    parser.add_argument("--version", action="version", version=f"gbfs-toolkit {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_audit = sub.add_parser("audit", help="semantic A1–A7 audit of a station_information feed")
    p_audit.add_argument("source", help="path or URL to station_information.json")
    p_audit.add_argument("--system-id", default="system", dest="system_id")
    p_audit.add_argument("--gbfs-version", default="2.x", dest="gbfs_version")
    p_audit.add_argument("--out", help="write the per-station verdict to this CSV")
    p_audit.set_defaults(func=_cmd_audit)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

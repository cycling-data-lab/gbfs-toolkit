"""Command-line interface: ``gbfs audit`` and the experimental data-lake commands.

``gbfs audit <station_information.json>`` is the semantic counterpart to MobilityData's syntactic
``gbfs-validator``. Four experimental commands work on collected data: ``gbfs collect`` (poll
feeds politely and write day files), ``gbfs quality`` (daily coverage and incidents),
``gbfs release`` (freeze a closed period into a depositable folder) and ``gbfs verify`` (check a
release or a data manifest). Run ``gbfs <command> --help`` for each.

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
from pathlib import Path

from gbfs_toolkit import __version__
from gbfs_toolkit.audit import audit_static
from gbfs_toolkit.core.errors import GBFSError
from gbfs_toolkit.core.models import AUDIT_FLAGS, RULES
from gbfs_toolkit.io.normalize import to_canonical_station_info

__all__ = [
    "main",
]


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


# --------------------------------------------------------------------------------------
# Experimental data-lake commands: collect, quality, release, verify
# --------------------------------------------------------------------------------------


def _read_systems(args: argparse.Namespace) -> dict[str, str]:
    """Systems from ``--system ID=URL`` (repeatable) and ``--systems-file`` (CSV or JSON)."""
    systems: dict[str, str] = {}
    for item in args.system or []:
        sid, sep, url = item.partition("=")
        if not sep or not sid or not url:
            raise ValueError(f"--system expects ID=URL, got {item!r}")
        systems[sid.strip()] = url.strip()
    if args.systems_file:
        import pandas as pd

        path = Path(args.systems_file)
        if path.suffix.lower() == ".json":
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict):
                raise ValueError(f"{path}: expected a JSON object {{system_id: url}}")
            systems.update({str(k): str(v) for k, v in loaded.items()})
        else:
            table = pd.read_csv(path, dtype=str)
            url_col = next(
                (c for c in ("auto_discovery_url", "gbfs_url", "url") if c in table.columns), None
            )
            if "system_id" not in table.columns or url_col is None:
                raise ValueError(
                    f"{path}: needs a system_id column and one of auto_discovery_url, gbfs_url, url"
                )
            systems.update(
                {
                    str(s): str(u)
                    for s, u in zip(table["system_id"], table[url_col], strict=True)
                    if isinstance(u, str)
                }
            )
    if not systems:
        raise ValueError("no system given: use --system ID=URL or --systems-file")
    return systems


def _cmd_collect(args: argparse.Namespace) -> int:
    from gbfs_toolkit.collect import Collector

    collector = Collector(
        _read_systems(args),
        args.out,
        user_agent=args.user_agent,
        feeds=args.feeds,
        timeout=args.timeout,
        min_interval=args.min_interval,
        respect_ttl=not args.no_ttl,
        max_workers=args.workers,
    )
    bounded = args.duration is not None or args.iterations is not None
    failed = 0

    def show(i: int, result) -> None:
        nonlocal failed
        failed += int((result["outcome"] == "failed").sum())
        counts = result["outcome"].value_counts().to_dict()
        print(
            f"poll {i}: {int(result['rows'].sum())} row(s); "
            + ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))
        )

    if args.metadata:
        meta = collector.poll_metadata()
        failed += int((meta["outcome"] == "failed").sum())
        print(
            "metadata: "
            + ", ".join(f"{k} {v}" for k, v in sorted(meta["outcome"].value_counts().items()))
        )
    if args.interval is None and not bounded:
        result = collector.poll_once()
        show(1, result)
        for r in result[result["outcome"] == "failed"].itertuples():
            print(f"  {r.system_id} {r.feed}: {r.error}", file=sys.stderr)
    else:
        summary = collector.run(
            interval=args.interval or 60.0,
            duration=args.duration,
            max_iterations=args.iterations,
            on_poll=show,
        )
        print(f"done: {summary['iterations']} poll(s), {summary['rows']} row(s)")
    return 1 if failed else 0


def _load_snapshots(args: argparse.Namespace):
    from gbfs_toolkit.collect import read_collected
    from gbfs_toolkit.store import read_lake

    root = Path(args.path)
    layout = args.layout
    if layout == "auto":
        layout = "lake" if any(root.glob("system_id=*")) else "collected"
    if layout == "lake":
        import pandas as pd

        end = None if args.end is None else pd.Timestamp(args.end, tz="UTC") + pd.Timedelta(days=1)
        return read_lake(root, systems=args.systems, start=args.start, end=end), "observed_at_utc"
    return (
        read_collected(root, args.kind, systems=args.systems, start=args.start, end=args.end),
        "fetched_at",
    )


def _cmd_quality(args: argparse.Namespace) -> int:
    from gbfs_toolkit.quality import STATUSES, assess, read_incidents, write_incidents

    snaps, time_col = _load_snapshots(args)
    if snaps.empty:
        print(f"gbfs: no snapshots found under {args.path}", file=sys.stderr)
        return 2
    known = read_incidents(args.incidents) if args.incidents else None
    options = {"ok_threshold_pct": args.threshold, "poll_resolution": args.poll_resolution}
    if args.expected_polls:
        options["expected_polls"] = args.expected_polls
    report = assess(
        snaps, known_incidents=known, time_col=time_col, end=args.end, start=args.start, **options
    )
    cov = report.coverage
    table = (
        cov.pivot_table(
            index="system_id", columns="status", values="date_utc", aggfunc="count", fill_value=0
        )
        .reindex(columns=list(STATUSES), fill_value=0)
        .assign(days=lambda t: t.sum(axis=1))
    )
    table["mean_completeness_pct"] = cov.groupby("system_id")["completeness_pct"].mean().round(1)
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        cov.to_csv(out / "daily_coverage.csv", index=False)
        write_incidents(report.incidents, out / "incidents.json")
    if args.json:
        print(
            json.dumps(
                {
                    "summary": report.summary(),
                    "systems": json.loads(table.reset_index().to_json(orient="records")),
                },
                indent=2,
            )
        )
    else:
        print(f"gbfs-toolkit {__version__}: coverage of {args.path}")
        print(table.reset_index().to_string(index=False))
        s = report.summary()
        print(f"{len(report.incidents)} incident(s): {s['incidents_by_cause'] or 'none'}")
        if args.out:
            print(f"  written to {args.out}")
    not_ok = int((cov["status"] != "ok").sum())
    return 1 if (args.strict and not_ok) else 0


def _cmd_release(args: argparse.Namespace) -> int:
    from gbfs_toolkit.release import freeze_release

    info = freeze_release(
        args.lake,
        args.out,
        name=args.name,
        start=args.start,
        end=args.end,
        systems=args.systems,
        table=args.table,
        title=args.title,
        license=args.license,
        incidents=args.incidents,
        croissant=not args.no_croissant,
        allow_open_period=args.allow_open_period,
    )
    print(
        f"release {info['name']}: {info['rows']} row(s), {info['files']} file(s), "
        f"systems {', '.join(info['systems'])} -> {info['path']}"
    )
    print(
        "nothing was uploaded; check the licence and the README, then deposit the folder yourself"
    )
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    path = Path(args.path)
    if path.is_dir():
        from gbfs_toolkit.release import verify_release

        report = verify_release(path, strict=False, deep=args.deep)
        for kind in ("missing", "mismatched", "unlisted"):
            for rel in report[kind]:
                print(f"  {kind}: {rel}", file=sys.stderr)
        if "deep" in report and not all(report["deep"].values()):
            print(f"  content differs from data_manifest.json: {report['deep']}", file=sys.stderr)
        print(
            f"{'OK' if report['ok'] else 'FAILED'}: {report['checked']} file(s) checked in {path}"
        )
        return 0 if report["ok"] else 1
    from gbfs_toolkit.repro import read_manifest, verify_manifest

    manifest = read_manifest(path)
    if not args.data:
        raise ValueError("verifying a manifest needs --data (a Parquet file, folder or lake)")
    result = verify_manifest(manifest, args.data, strict=False)
    print(f"{'OK' if all(result.values()) else 'FAILED'}: table {manifest['table']!r}, {result}")
    return 0 if all(result.values()) else 1


def _add_data_commands(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "collect",
        help="poll GBFS feeds politely and write one Parquet file per system and day (experimental)",
        description="(Experimental.) Poll the station (and vehicle) feeds of some systems, respecting each feed's ttl, "
        "and write the snapshots under OUT/<feed>/<system>/<day>.parquet. A value a feed leaves out is "
        "stored empty, never 0 or true. With no --interval, --duration or --iterations, polls once.",
    )
    p.add_argument(
        "--system",
        action="append",
        metavar="ID=URL",
        help="a system and its gbfs.json URL (repeatable)",
    )
    p.add_argument(
        "--systems-file", help="CSV (system_id + auto_discovery_url|gbfs_url|url) or JSON {id: url}"
    )
    p.add_argument("--out", required=True, help="folder for the day files")
    p.add_argument(
        "--user-agent",
        required=True,
        dest="user_agent",
        help="who you are, with a contact, e.g. 'my-lab/1.0 (mailto:me@example.org)'",
    )
    p.add_argument(
        "--feeds",
        nargs="+",
        choices=("station_status", "vehicle_status"),
        default=["station_status"],
    )
    p.add_argument(
        "--interval",
        type=float,
        help="seconds between polls (then also give --duration or --iterations, or stop with Ctrl-C)",
    )
    p.add_argument("--duration", type=float, help="stop after this many seconds")
    p.add_argument("--iterations", type=int, help="stop after this many polls")
    p.add_argument(
        "--min-interval",
        type=float,
        default=1.0,
        dest="min_interval",
        help="never ask one feed twice within this many seconds (default 1)",
    )
    p.add_argument(
        "--no-ttl",
        action="store_true",
        dest="no_ttl",
        help="do not wait for the feed's ttl (you then own the load you put on it)",
    )
    p.add_argument("--timeout", type=float, default=15.0, help="seconds per request (default 15)")
    p.add_argument("--workers", type=int, default=4, help="systems polled in parallel (default 4)")
    p.add_argument(
        "--metadata", action="store_true", help="also keep dated versions of the metadata feeds"
    )
    p.set_defaults(func=_cmd_collect)

    q = sub.add_parser(
        "quality",
        help="daily coverage, collection gaps and incidents of collected snapshots (experimental)",
        description="(Experimental.) Per system and UTC day: polls expected and obtained, and a status (ok, partial, "
        "outage_collector, outage_operator). PATH is a collect folder or a store lake.",
    )
    q.add_argument("path", help="a `gbfs collect` output folder or a lake")
    q.add_argument("--layout", choices=("auto", "collected", "lake"), default="auto")
    q.add_argument(
        "--kind",
        choices=("station_status", "vehicle_status"),
        default="station_status",
        help="which collected feed to read (collect layout only)",
    )
    q.add_argument("--systems", nargs="+", help="only these systems")
    q.add_argument("--start", help="first UTC day")
    q.add_argument("--end", help="last UTC day (leave out today's, still being collected)")
    q.add_argument(
        "--expected-polls",
        type=int,
        dest="expected_polls",
        help="polls per day (default: one per --poll-resolution)",
    )
    q.add_argument(
        "--poll-resolution",
        default="1min",
        dest="poll_resolution",
        help="poll slot, e.g. 1min or 15min",
    )
    q.add_argument(
        "--threshold",
        type=float,
        default=95.0,
        help="completeness %% from which a day is ok (default 95)",
    )
    q.add_argument("--incidents", help="a registry (.json or .csv) of incidents you know of")
    q.add_argument("--out", help="write daily_coverage.csv and incidents.json to this folder")
    q.add_argument("--json", action="store_true", help="machine-readable output")
    q.add_argument("--strict", action="store_true", help="exit 1 if any system-day is not ok")
    q.set_defaults(func=_cmd_quality)

    r = sub.add_parser(
        "release",
        help="freeze a closed period of a lake into a folder to deposit (experimental)",
        description="(Experimental.) Write OUT with the data cut at the period, daily coverage, incidents, a data "
        "package, a README and SHA256SUMS. Uploads nothing; the licence is yours to choose.",
    )
    r.add_argument("lake", help="a lake written by gbfs_toolkit.store")
    r.add_argument("out", help="a new, empty folder")
    r.add_argument("--name", required=True, help="release name and version, e.g. demo-2026-03")
    r.add_argument("--start", required=True, help="first UTC day (inclusive)")
    r.add_argument("--end", required=True, help="last UTC day (inclusive); must be in the past")
    r.add_argument("--systems", nargs="+", help="only these systems")
    r.add_argument("--table", default="station_status")
    r.add_argument("--title")
    r.add_argument("--license", help="e.g. CC0-1.0, CC-BY-4.0, ODbL-1.0 (no default)")
    r.add_argument("--incidents", help="a registry (.json or .csv) of incidents you know of")
    r.add_argument("--no-croissant", action="store_true", dest="no_croissant")
    r.add_argument("--allow-open-period", action="store_true", dest="allow_open_period")
    r.set_defaults(func=_cmd_release)

    v = sub.add_parser(
        "verify",
        help="check a release folder (SHA256SUMS) or a data manifest (experimental)",
        description="(Experimental.) With a folder: every file must match SHA256SUMS and none may be unlisted "
        "(--deep also re-reads the data and compares its fingerprint). With a manifest file: "
        "compare --data with the rows and fingerprint it records. Exit 0 if it matches, 1 if not.",
    )
    v.add_argument("path", help="a release folder, or a data_manifest.json")
    v.add_argument("--data", help="the data to check against a manifest (file, folder or lake)")
    v.add_argument(
        "--deep", action="store_true", help="also compare the content fingerprint (release folders)"
    )
    v.set_defaults(func=_cmd_verify)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="gbfs",
        description="Semantic audit of GBFS feeds (audit) and tools for collected data "
        "(collect, quality, release, verify: experimental). Run `gbfs <command> --help`.",
    )
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
    _add_data_commands(sub)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except FileNotFoundError as e:
        print(f"gbfs: file not found: {e.filename}", file=sys.stderr)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        print(
            f"gbfs: could not parse JSON from {getattr(args, 'source', args.command)!r}: {e}",
            file=sys.stderr,
        )
    except urllib.error.URLError as e:
        print(
            f"gbfs: could not fetch {getattr(args, 'source', args.command)!r}: {e.reason}",
            file=sys.stderr,
        )
    except (GBFSError, OSError, ValueError, ImportError) as e:
        print(f"gbfs: {e}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

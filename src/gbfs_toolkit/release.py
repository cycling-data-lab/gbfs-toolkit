"""Freeze a closed period of a lake into a folder you can deposit anywhere.

!!! warning "Experimental"
    Part of the experimental data-lake modules added in 2.1.0: names, parameters and output
    columns may change in a minor release (see the API policy).

`freeze_release` takes a lake written by `gbfs_toolkit.store`, a **closed** UTC
period (it refuses a period that is not over) and some systems, and writes a new folder::

    <out>/data/<table>/system_id=<id>/year=2026/month=03/data.parquet   cut at the period's bounds
    <out>/daily_coverage.csv, daily_coverage.parquet                     polls expected and obtained per day
    <out>/incidents.csv, incidents.json                                  the registry for the period
    <out>/data_manifest.json                                             rows and content fingerprint
    <out>/datapackage.json                                               Frictionless Data Package
    <out>/croissant.json                                                 Croissant metadata (optional)
    <out>/README.md                                                      what is in it, coverage, licence
    <out>/SHA256SUMS                                                     one checksum per file

It **uploads nothing and registers nothing**: depositing the folder (Zenodo, Dataverse, a bucket)
is yours to do, and so is the choice of licence. `verify_release` checks a folder against its
``SHA256SUMS`` (the same file ``sha256sum -c`` reads), which is what a downstream user runs.

The coverage and incidents come from `gbfs_toolkit.quality`, computed on the released rows,
so the README states honestly which days are complete and which are not. The Croissant file is a
minimal description (record set, fields, the Parquet file set); check it with the MLCommons
validator before relying on it. Needs ``pip install gbfs-toolkit[parquet]``.

Examples
--------
>>> import tempfile, pandas as pd
>>> from gbfs_toolkit.store import write_lake
>>> from gbfs_toolkit.release import freeze_release, verify_release
>>> t = pd.date_range("2026-03-01", periods=1440, freq="min", tz="UTC")
>>> snaps = pd.DataFrame({"system_id": "demo", "station_id": "s1", "observed_at_utc": t,
...                       "num_bikes_available": 3, "num_docks_available": 5})
>>> with tempfile.TemporaryDirectory() as tmp:
...     _ = write_lake(snaps, tmp + "/lake")
...     info = freeze_release(tmp + "/lake", tmp + "/release", name="demo-2026-03-01",
...                           start="2026-03-01", end="2026-03-01", license="CC0-1.0")
...     report = verify_release(tmp + "/release")
>>> info["rows"], report["ok"]
(1440, True)
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pandas as pd

from gbfs_toolkit.core._common import atomic_write, check, require_pyarrow, to_utc
from gbfs_toolkit.core.errors import GBFSValidationError

__all__ = [
    "CHECKSUM_FILE",
    "freeze_release",
    "verify_release",
    "table_schema",
]

_log = logging.getLogger(__name__)

CHECKSUM_FILE = "SHA256SUMS"
_LICENSES = {
    "CC0-1.0": ("Creative Commons Zero 1.0", "https://creativecommons.org/publicdomain/zero/1.0/"),
    "CC-BY-4.0": (
        "Creative Commons Attribution 4.0",
        "https://creativecommons.org/licenses/by/4.0/",
    ),
    "ODbL-1.0": ("Open Database License 1.0", "https://opendatacommons.org/licenses/odbl/1-0/"),
    "ODC-By-1.0": (
        "Open Data Commons Attribution 1.0",
        "https://opendatacommons.org/licenses/by/1-0/",
    ),
    "etalab-2.0": (
        "Licence Ouverte 2.0",
        "https://www.etalab.gouv.fr/licence-ouverte-open-licence/",
    ),
}
_STATUS_LABEL = {
    "ok": "complete",
    "partial": "partial",
    "outage_collector": "collector outage",
    "outage_operator": "operator feed silent",
}
_CROISSANT_CONTEXT: dict[str, Any] = {
    "@language": "en",
    "@vocab": "https://schema.org/",
    "citeAs": "cr:citeAs",
    "column": "cr:column",
    "conformsTo": "dct:conformsTo",
    "cr": "http://mlcommons.org/croissant/",
    "data": {"@id": "cr:data", "@type": "@json"},
    "dataType": {"@id": "cr:dataType", "@type": "@vocab"},
    "dct": "http://purl.org/dc/terms/",
    "extract": "cr:extract",
    "field": "cr:field",
    "fileObject": "cr:fileObject",
    "fileProperty": "cr:fileProperty",
    "fileSet": "cr:fileSet",
    "format": "cr:format",
    "includes": "cr:includes",
    "isLiveDataset": "cr:isLiveDataset",
    "jsonPath": "cr:jsonPath",
    "key": "cr:key",
    "md5": "cr:md5",
    "parentField": "cr:parentField",
    "path": "cr:path",
    "recordSet": "cr:recordSet",
    "references": "cr:references",
    "regex": "cr:regex",
    "repeated": "cr:repeated",
    "replace": "cr:replace",
    "sc": "https://schema.org/",
    "separator": "cr:separator",
    "source": "cr:source",
    "subField": "cr:subField",
    "transform": "cr:transform",
}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def table_schema(df: pd.DataFrame, *, extra_text: Sequence[str] = ()) -> dict[str, Any]:
    """A Frictionless *Table Schema* (field names and types) for a frame.

    Types are ``integer``, ``number``, ``boolean``, ``datetime``, ``date`` or ``string``; an
    empty cell is a missing value (``missingValues`` is ``[""]``). ``extra_text`` names more
    string fields (the partition column, which lives in the folder name).

    Examples
    --------
    >>> import pandas as pd
    >>> schema = table_schema(pd.DataFrame({"n": pd.array([1, None], dtype="Int64"), "s": ["a", "b"]}))
    >>> [(f["name"], f["type"]) for f in schema["fields"]]
    [('n', 'integer'), ('s', 'string')]
    """
    fields = []
    for name in df.columns:
        s = df[name]
        if pd.api.types.is_bool_dtype(s.dtype):
            kind = "boolean"
        elif pd.api.types.is_integer_dtype(s.dtype):
            kind = "integer"
        elif pd.api.types.is_float_dtype(s.dtype):
            kind = "number"
        elif pd.api.types.is_datetime64_any_dtype(s.dtype):
            kind = "datetime"
        else:
            kind = "string"
        fields.append({"name": str(name), "type": kind})
    have = {f["name"] for f in fields}
    fields += [{"name": n, "type": "string"} for n in extra_text if n not in have]
    return {"fields": fields, "missingValues": [""]}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9._-]+", "-", text.lower()).strip("-") or "dataset"


def _month_span(start: pd.Timestamp, end_exclusive: pd.Timestamp) -> list[tuple[int, int]]:
    out, y, m = [], start.year, start.month
    last = end_exclusive - pd.Timedelta(1, "ns")
    while (y, m) <= (last.year, last.month):
        out.append((y, m))
        y, m = (y + (m == 12), m % 12 + 1)
    return out


def _incident_table(known: Any) -> pd.DataFrame:
    from gbfs_toolkit.quality import incident_registry, read_incidents

    if known is None:
        return incident_registry(None)
    if isinstance(known, (str, Path)):
        return read_incidents(known)
    return incident_registry(known)


def freeze_release(
    lake: str | Path,
    out_dir: str | Path,
    *,
    name: str,
    start: str | pd.Timestamp,
    end: str | pd.Timestamp,
    systems: Sequence[str] | None = None,
    table: str = "station_status",
    time_col: str | None = None,
    title: str | None = None,
    description: str | None = None,
    license: str | None = None,
    producers: Sequence[Mapping[str, str]] | None = None,
    incidents: Any = None,
    coverage_options: Mapping[str, Any] | None = None,
    croissant: bool = True,
    allow_open_period: bool = False,
    today: dt.date | None = None,
) -> dict[str, Any]:
    """Write a frozen release of ``lake`` for the UTC days ``start`` to ``end`` (both inclusive).

    Parameters
    ----------
    lake : path
        A `gbfs_toolkit.store` lake.
    out_dir : path
        The release folder. It must not exist or must be empty: a release is written once.
    name : str
        The release name and version (``demo-2026-03``).
    systems : sequence of str, optional
        Systems to include (default: all that have data in the period).
    table : str, default "station_status"
        The table's name in the folder layout and the metadata.
    time_col : str, optional
        The lake's time column (default: the one recorded in ``lake.json``).
    title, description : str, optional
        For the data package and the README.
    license : str, optional
        An SPDX-style identifier (``CC0-1.0``, ``CC-BY-4.0``, ``ODbL-1.0``, ``ODC-By-1.0``,
        ``etalab-2.0`` are known by name and link). Choose it yourself; there is no default. If
        omitted the README says the release has **no licence declared**.
    producers : sequence of dict, optional
        Who published the original feeds, to credit: dicts with ``system_id`` and any of
        ``producer``, ``license``, ``license_url``, ``source``. Listed in the README.
    incidents : registry, path or None
        Incidents you know of (see `gbfs_toolkit.quality`); the ones that overlap the
        period are kept, and those the data reveal (collection gaps, silent feeds) are added.
    coverage_options : mapping, optional
        Options of `gbfs_toolkit.quality.daily_coverage` (``expected_polls``,
        ``poll_resolution``, ``ok_threshold_pct``).
    croissant : bool, default True
        Also write ``croissant.json``.
    allow_open_period : bool, default False
        Allow ``end`` to be today or later. A period still being collected is not a release.

    Returns
    -------
    dict
        ``path, name, rows, systems, files, period``.

    Raises
    ------
    GBFSValidationError
        For an open period, a non-empty ``out_dir``, or no data in the period.
    """
    require_pyarrow("freeze_release")
    from gbfs_toolkit.quality import (
        daily_coverage,
        detect_incidents,
        incidents_overlapping,
        write_incidents,
    )
    from gbfs_toolkit.repro import MANIFEST_FILE, create_manifest, write_manifest
    from gbfs_toolkit.store import list_partitions, read_lake, read_lake_metadata, write_lake

    lo = to_utc([start]).iloc[0].normalize()
    last_day = to_utc([end]).iloc[0].normalize()
    hi = last_day + pd.Timedelta(days=1)
    check(last_day >= lo, f"the period ends ({last_day.date()}) before it starts ({lo.date()})")
    now_day = today or dt.datetime.now(dt.timezone.utc).date()
    check(
        allow_open_period or last_day.date() < now_day,
        f"the period must be closed: it ends on {last_day.date()}, and today is {now_day} (UTC)",
    )
    out = Path(out_dir)
    check(
        not out.exists() or not any(out.iterdir()),
        f"{out} exists and is not empty; a release is written once, into a new folder",
    )
    meta = read_lake_metadata(lake)
    tcol = time_col or meta.get("time_column", "observed_at_utc")
    wanted = None if systems is None else {str(s) for s in systems}
    parts = list_partitions(lake)
    span = set(_month_span(lo, hi))
    parts = parts[
        [
            (wanted is None or s in wanted) and (y, m) in span
            for s, y, m in zip(parts["system_id"], parts["year"], parts["month"], strict=True)
        ]
    ]
    out.mkdir(parents=True, exist_ok=True)
    data_root = out / "data" / table
    rows_total = 0
    coverage_inputs: list[pd.DataFrame] = []
    for system, year, month in zip(parts["system_id"], parts["year"], parts["month"], strict=True):
        part_lo = max(lo, pd.Timestamp(year=int(year), month=int(month), day=1, tz="UTC"))
        part_hi = min(
            hi,
            pd.Timestamp(
                year=int(year) + (month == 12), month=int(month) % 12 + 1, day=1, tz="UTC"
            ),
        )
        df = read_lake(lake, systems=[system], start=part_lo, end=part_hi, time_col=tcol)
        if df.empty:
            continue
        write_lake(df, data_root, mode="replace", time_col=tcol)
        rows_total += len(df)
        keep = [
            c
            for c in ("system_id", tcol, "num_bikes_available", "num_docks_available")
            if c in df.columns
        ]
        coverage_inputs.append(df[keep])
    check(rows_total > 0, "nothing to freeze: the lake has no rows for these systems and days")
    released_systems = sorted(
        {str(s) for s in parts["system_id"] if (data_root / f"system_id={s}").exists()}
    )
    snapshots = pd.concat(coverage_inputs, ignore_index=True)

    cov_opts = dict(coverage_options or {})
    coverage = daily_coverage(snapshots, time_col=tcol, start=lo, end=last_day, **cov_opts)
    known = incidents_overlapping(_incident_table(incidents), lo, hi, released_systems)
    registry = incidents_overlapping(
        detect_incidents(
            coverage,
            snapshots,
            known=known,
            time_col=tcol,
            min_collector_gap=cov_opts.get("min_collector_gap", "60min"),
        ),
        lo,
        hi,
        released_systems,
    )
    cov_out = coverage.copy()
    cov_out["date_utc"] = pd.to_datetime(cov_out["date_utc"])
    cov_out.to_csv(out / "daily_coverage.csv", index=False)
    cov_out.to_parquet(out / "daily_coverage.parquet", index=False, compression="zstd")
    write_incidents(registry, out / "incidents.json")
    write_incidents(registry, out / "incidents.csv")

    data_files = sorted(p.relative_to(out).as_posix() for p in data_root.rglob("*.parquet"))
    full = read_lake(data_root, time_col=tcol)
    manifest = create_manifest(
        full, table=table, systems=released_systems, start=lo, end=last_day, source=name
    )
    write_manifest(manifest, out / MANIFEST_FILE)
    schema = table_schema(full, extra_text=["system_id"])
    licenses = []
    if license:
        label, url = _LICENSES.get(license, (license, None))
        licenses = [{"name": license, "title": label, **({"path": url} if url else {})}]
    else:
        _log.warning("freeze_release: no licence declared; the README says so")
    created = pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ")
    heading = title or f"GBFS {table.replace('_', ' ')}, {lo.date()} to {last_day.date()}"
    package = {
        "profile": "tabular-data-package",
        "name": _slug(name),
        "title": heading,
        "version": name,
        "created": created,
        "description": description
        or (
            f"Snapshots of {len(released_systems)} bike-share system(s) for the UTC days {lo.date()} "
            f"to {last_day.date()}, with their daily coverage and incidents. `system_id` is the "
            "name of the folder a file is in."
        ),
        **({"licenses": licenses} if licenses else {}),
        "resources": [
            {
                "name": table,
                "type": "table",
                "format": "parquet",
                "mediatype": "application/vnd.apache.parquet",
                "path": data_files,
                "schema": schema,
            },
            {
                "name": "daily-coverage",
                "type": "table",
                "format": "csv",
                "mediatype": "text/csv",
                "path": "daily_coverage.csv",
                "schema": table_schema(cov_out),
            },
            {
                "name": "incidents",
                "type": "table",
                "format": "json",
                "mediatype": "application/json",
                "path": "incidents.json",
            },
        ],
    }
    _write_json(out / "datapackage.json", package)
    if croissant:
        _write_json(
            out / "croissant.json", _croissant(package, table, schema, licenses, created, name)
        )
    (out / "README.md").write_text(
        _readme(
            heading,
            name,
            table,
            lo,
            last_day,
            released_systems,
            data_files,
            rows_total,
            coverage,
            registry,
            licenses,
            producers or [],
            croissant,
        ),
        encoding="utf-8",
    )
    _write_checksums(out)
    _log.info("release %s: %d rows, %d file(s) -> %s", name, rows_total, len(data_files), out)
    return {
        "path": out,
        "name": name,
        "rows": rows_total,
        "systems": released_systems,
        "files": len(data_files),
        "period": (str(lo.date()), str(last_day.date())),
    }


def _write_json(path: Path, obj: Any) -> None:
    atomic_write(
        path,
        lambda tmp: tmp.write_text(
            json.dumps(obj, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
        ),
    )


_CROISSANT_TYPES = {
    "integer": "sc:Integer",
    "number": "sc:Float",
    "boolean": "sc:Boolean",
    "datetime": "sc:DateTime",
    "string": "sc:Text",
}


def _croissant(
    package: dict[str, Any],
    table: str,
    schema: dict[str, Any],
    licenses: list[dict[str, str]],
    created: str,
    name: str,
) -> dict[str, Any]:
    fields = [
        {
            "@type": "cr:Field",
            "@id": f"{table}/{f['name']}",
            "name": f["name"],
            "dataType": _CROISSANT_TYPES.get(f["type"], "sc:Text"),
            "source": {"fileSet": {"@id": "parquet-files"}, "extract": {"column": f["name"]}},
        }
        for f in schema["fields"]
    ]
    doc: dict[str, Any] = {
        "@context": _CROISSANT_CONTEXT,
        "@type": "sc:Dataset",
        "conformsTo": "http://mlcommons.org/croissant/1.0",
        "name": package["name"],
        "description": package["description"],
        "version": name,
        "datePublished": created,
        "distribution": [
            {
                "@type": "cr:FileSet",
                "@id": "parquet-files",
                "name": "parquet-files",
                "encodingFormat": "application/vnd.apache.parquet",
                "includes": f"data/{table}/**/*.parquet",
            },
            {
                "@type": "cr:FileObject",
                "@id": "daily_coverage.csv",
                "name": "daily_coverage.csv",
                "contentUrl": "daily_coverage.csv",
                "encodingFormat": "text/csv",
            },
        ],
        "recordSet": [{"@type": "cr:RecordSet", "@id": table, "name": table, "field": fields}],
    }
    if licenses and licenses[0].get("path"):
        doc["license"] = licenses[0]["path"]
    return doc


def _readme(
    heading: str,
    name: str,
    table: str,
    lo: pd.Timestamp,
    hi: pd.Timestamp,
    systems: list[str],
    files: list[str],
    rows: int,
    coverage: pd.DataFrame,
    registry: pd.DataFrame,
    licenses: list[dict[str, str]],
    producers: Sequence[Mapping[str, str]],
    croissant: bool,
) -> str:
    n = f"{rows:,}".replace(",", " ")
    lines = [
        f"# {heading}",
        "",
        f"Release `{name}`: UTC days {lo.date()} to {hi.date()} (a closed period), "
        f"{len(systems)} system(s), {n} rows.",
        "",
        "## Contents",
        "",
        f"- `data/{table}/system_id=<id>/year=YYYY/month=MM/data.parquet`: {len(files)} Parquet "
        "file(s) (zstd), cut at the period's bounds. The system is the folder name.",
        "- `daily_coverage.csv` / `.parquet`: one row per system and UTC day: polls expected and "
        "obtained, completeness and a status.",
        "- `incidents.csv` / `.json`: collection gaps, silent feeds and declared incidents of the period.",
        "- `data_manifest.json`: row count and content fingerprint (see `gbfs_toolkit.repro`).",
        "- `datapackage.json`: Frictionless Data Package with the Table Schema of each file.",
    ]
    if croissant:
        lines.append("- `croissant.json`: minimal Croissant metadata (unvalidated).")
    lines += ["- `SHA256SUMS`: one checksum per file.", "", "## Coverage", ""]
    lines += [
        "| System | Days | Complete | Partial | Collector outage | Feed silent | Mean completeness |",
        "|---|---|---|---|---|---|---|",
    ]
    for system, g in coverage.groupby("system_id", sort=True):
        c = {k: int((g["status"] == k).sum()) for k in _STATUS_LABEL}
        lines.append(
            f"| {system} | {len(g)} | {c['ok']} | {c['partial']} | {c['outage_collector']} | "
            f"{c['outage_operator']} | {g['completeness_pct'].mean():.1f} % |"
        )
    lines += [
        "",
        "A day is *complete* when at least the threshold share of the expected polls arrived "
        "(see `daily_coverage.csv`); a partial day is not a day without activity.",
        "",
        "## Gaps and incidents",
        "",
    ]
    if registry.empty:
        lines.append("- none recorded")
    for r in registry.itertuples(index=False):
        end = "ongoing" if pd.isna(r.end_utc) else f"{r.end_utc:%Y-%m-%d %H:%M}Z"
        lines.append(
            f"- {r.start_utc:%Y-%m-%d %H:%M}Z to {end} ({r.scope}, {r.cause}): {r.summary}"
        )
    lines += ["", "## Licence", ""]
    if licenses:
        lic = licenses[0]
        link = f" ({lic['path']})" if lic.get("path") else ""
        lines.append(f"This release is published under **{lic['title']}**{link}.")
    else:
        lines.append(
            "**No licence is declared for this release.** Add one, and check the licences of "
            "the original feeds below, before depositing it."
        )
    if producers:
        lines += [
            "",
            "### Producers to credit",
            "",
            "| System | Producer | Licence of the original feed | Source |",
            "|---|---|---|---|",
        ]
        for p in producers:
            lines.append(
                f"| `{p.get('system_id', '')}` | {p.get('producer', '')} | "
                f"{p.get('license_url') or p.get('license', '')} | {p.get('source', '')} |"
            )
    lines += [
        "",
        "## Verify",
        "",
        "```bash",
        "sha256sum -c SHA256SUMS",
        "```",
        "",
        "or `gbfs verify .` with gbfs-toolkit.",
        "",
        "## Read",
        "",
        "```python",
        "import pandas as pd",
        f"df = pd.read_parquet('data/{table}')   # system_id comes from the folder names",
        "```",
        "",
        "```python",
        "import duckdb",
        f"duckdb.sql(\"SELECT * FROM read_parquet('data/{table}/*/*/*/*.parquet', hive_partitioning = true) LIMIT 10\")",
        "```",
        "",
    ]
    return "\n".join(lines)


def _write_checksums(root: Path) -> None:
    files = sorted(
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file() and p.name != CHECKSUM_FILE
    )
    text = "".join(f"{_sha256(root / rel)}  {rel}\n" for rel in files)
    (root / CHECKSUM_FILE).write_text(text, encoding="utf-8")


def verify_release(
    directory: str | Path, *, strict: bool = True, deep: bool = False
) -> dict[str, Any]:
    """Check a release folder against its ``SHA256SUMS``.

    Every listed file must exist with the recorded checksum, and no file may be present that is
    not listed. With ``deep=True`` the table is also read back and compared with
    ``data_manifest.json`` (rows and content fingerprint), which catches a file that was
    re-encoded without being altered.

    Returns
    -------
    dict
        ``ok`` (bool), ``checked`` (count), ``missing``, ``mismatched`` and ``unlisted`` (lists
        of paths). With ``strict`` (the default) a problem raises ``GBFSValidationError`` naming
        them.

    Examples
    --------
    >>> verify_release("/nonexistent")  # doctest: +IGNORE_EXCEPTION_DETAIL
    Traceback (most recent call last):
    GBFSValidationError: no SHA256SUMS in /nonexistent
    """
    root = Path(directory)
    sums = root / CHECKSUM_FILE
    check(sums.is_file(), f"no {CHECKSUM_FILE} in {root}")
    listed: dict[str, str] = {}
    for n, line in enumerate(sums.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        m = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if m is None:
            raise GBFSValidationError(f"{sums}, line {n}: not a 'sha256  path' line")
        digest, rel = m.groups()
        if rel.startswith("/") or ".." in Path(rel).parts:
            raise GBFSValidationError(f"{sums}, line {n}: unsafe path {rel!r}")
        listed[rel] = digest
    missing = sorted(rel for rel in listed if not (root / rel).is_file())
    mismatched = sorted(
        rel for rel, d in listed.items() if rel not in missing and _sha256(root / rel) != d
    )
    present = {
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file() and p.name != CHECKSUM_FILE
    }
    unlisted = sorted(present - set(listed))
    problems = []
    if missing:
        problems.append(f"missing: {missing[:5]}")
    if mismatched:
        problems.append(f"changed: {mismatched[:5]}")
    if unlisted:
        problems.append(f"not in {CHECKSUM_FILE}: {unlisted[:5]}")
    report: dict[str, Any] = {
        "ok": not problems,
        "checked": len(listed) - len(missing),
        "missing": missing,
        "mismatched": mismatched,
        "unlisted": unlisted,
    }
    if deep and not problems and (root / "data_manifest.json").is_file():
        from gbfs_toolkit.repro import read_manifest, verify_manifest
        from gbfs_toolkit.store import read_lake

        manifest = read_manifest(root / "data_manifest.json")
        result = verify_manifest(
            manifest, read_lake(root / "data" / manifest["table"]), strict=False
        )
        report["deep"] = result
        if not all(result.values()):
            report["ok"] = False
            problems.append(f"content differs from data_manifest.json: {result}")
    if problems and strict:
        raise GBFSValidationError(
            f"{root} does not match its {CHECKSUM_FILE}: " + "; ".join(problems)
        )
    return report

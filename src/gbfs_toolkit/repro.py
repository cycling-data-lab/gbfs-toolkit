"""A data manifest and a content fingerprint, so an analysis can prove which data it read.

!!! warning "Experimental"
    Part of the experimental data-lake modules added in 2.1.0: names, parameters and output
    columns may change in a minor release (see the API policy).

An analysis that cites "the stations of one city in March" is only reproducible if someone can check
that the table they rebuilt is the table the authors used. The pieces here:

`fingerprint`
    a SHA-256 of a table's *content*. It does not depend on the order of the rows, on the file
    format, or on the tool that wrote the file: columns are taken by name, numbers are written
    with 12 significant digits (so ``1`` and ``1.0``, or a float that went through another
    tool, agree; **differences beyond the 12th digit are not detected, by design**), times as
    microseconds since 1970 UTC, booleans as 0 and 1, an empty value as ``∅``; each row is hashed
    (MD5), the hashes are sorted, and the sorted column names followed by the hashes are hashed
    again (SHA-256), so renaming a column changes the fingerprint.
`create_manifest` / `write_manifest` / `read_manifest`
    a small JSON file naming the table, the systems, the UTC days, the columns, the number of
    rows and the fingerprint;
`verify_manifest`
    the check, raising `gbfs_toolkit.core.errors.GBFSValidationError` when rows or
    fingerprint differ;
`materialize`
    read the data a manifest describes from a lake (`gbfs_toolkit.store`, a release's
    ``data/`` folder, or your own ``reader``), verify it, and keep a Parquet copy in a cache
    folder that git ignores;
`export_sample`
    a few stations of a table, a few megabytes, for a continuous-integration run that cannot
    hold the real data.

The documentation page gives the equivalent DuckDB expression, so a table fingerprinted here
and in SQL agree (a test checks it). Parquet needs
``pip install gbfs-toolkit[parquet]``.

Examples
--------
>>> import pandas as pd
>>> from gbfs_toolkit.repro import fingerprint
>>> a = pd.DataFrame({"x": [1, 2], "t": pd.to_datetime(["2026-01-01", "2026-01-02"], utc=True)})
>>> b = a.iloc[::-1].assign(x=[2.0, 1.0])[["t", "x"]]
>>> fingerprint(a) == fingerprint(b)
True
>>> fingerprint(a).startswith("sha256:")
True
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pandas as pd

from gbfs_toolkit.core._common import atomic_write, check, require_pyarrow, to_utc
from gbfs_toolkit.core.errors import GBFSValidationError

__all__ = [
    "MANIFEST_FORMAT",
    "MANIFEST_FILE",
    "fingerprint",
    "create_manifest",
    "write_manifest",
    "read_manifest",
    "verify_manifest",
    "materialize",
    "export_sample",
]

_log = logging.getLogger(__name__)

MANIFEST_FORMAT = "gbfs-toolkit-data-manifest/1"
MANIFEST_FILE = "data_manifest.json"
_EMPTY = "∅"


def _load(data: Any) -> pd.DataFrame:
    """A frame from a frame, a Parquet file, a folder of Parquet files or a lake."""
    if isinstance(data, pd.DataFrame):
        return data
    path = Path(data)
    require_pyarrow("fingerprint of a file")
    if path.is_dir() and any(path.glob("system_id=*/year=*/month=*/*.parquet")):
        from gbfs_toolkit.store import read_lake

        return read_lake(path)
    return pd.read_parquet(path)


def _column_text(s: pd.Series) -> pd.Series:
    """One column as the canonical text of each value (see the module description)."""
    kind = pd.api.types.infer_dtype(s, skipna=True)
    if pd.api.types.is_datetime64_any_dtype(s.dtype) or kind in ("date", "datetime", "datetime64"):
        t = pd.to_datetime(s, utc=True)
        micros = t.dt.as_unit("us").astype("int64")
        return micros.astype(str).where(t.notna(), _EMPTY)
    if (
        pd.api.types.is_bool_dtype(s.dtype)
        or pd.api.types.is_numeric_dtype(s.dtype)
        or kind in ("boolean", "integer", "floating", "mixed-integer-float", "decimal")
    ):
        num = pd.to_numeric(
            s.astype("Float64") if not pd.api.types.is_float_dtype(s.dtype) else s, errors="coerce"
        ).astype("float64")
        text = pd.Series(
            [_EMPTY if v != v else format(v, ".12g") for v in num.to_numpy()],
            index=s.index,
            dtype="object",
        )
        return text
    return s.astype("string").fillna(_EMPTY).astype("object")


def fingerprint(data: Any, *, exclude: Sequence[str] = ()) -> str:
    """The content fingerprint ``"sha256:<hex>"`` of a table (see the module description).

    Parameters
    ----------
    data : DataFrame, path, or lake folder
        A frame, a Parquet file, a folder of Parquet files, or a `gbfs_toolkit.store` lake.
    exclude : sequence of str
        Columns to leave out (storage keys such as ``year`` and ``month``, say).

    Examples
    --------
    >>> import pandas as pd
    >>> fingerprint(pd.DataFrame({"a": []})) == fingerprint(pd.DataFrame({"b": []}))
    False
    """
    df = _load(data)
    names = sorted(str(c) for c in df.columns if str(c) not in set(exclude))
    if not names:
        return "sha256:" + hashlib.sha256(b"").hexdigest()
    by_name = {str(c): c for c in df.columns}
    parts = [_column_text(df[by_name[n]].reset_index(drop=True)) for n in names]
    rows = parts[0].str.cat(parts[1:], sep="|") if len(parts) > 1 else parts[0]
    hashes = sorted(hashlib.md5(r.encode("utf-8")).hexdigest() for r in rows)
    header = "|".join(names) + "\n"
    return "sha256:" + hashlib.sha256((header + "".join(hashes)).encode("utf-8")).hexdigest()


def _day(value: Any) -> str | None:
    return None if value is None else to_utc([value]).iloc[0].strftime("%Y-%m-%d")


def create_manifest(
    data: Any,
    *,
    table: str,
    systems: Sequence[str] | None = None,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
    columns: Sequence[str] | None = None,
    exclude: Sequence[str] = (),
    source: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Describe ``data`` (what an analysis read) and fingerprint it.

    ``systems``, ``start`` and ``end`` (UTC days, both inclusive) and ``columns`` record how the
    table was selected, so `materialize` can select it again. ``source`` is free text: a
    release name, a lake path, a DOI. Nothing in the manifest depends on a machine or a user.

    Examples
    --------
    >>> import pandas as pd
    >>> m = create_manifest(pd.DataFrame({"x": [1, 2, 3]}), table="demo", start="2026-01-01", end="2026-01-31")
    >>> m["rows"], m["start_utc"], m["format"]
    (3, '2026-01-01', 'gbfs-toolkit-data-manifest/1')
    """
    from gbfs_toolkit import __version__

    df = _load(data)
    manifest: dict[str, Any] = {
        "format": MANIFEST_FORMAT,
        "table": table,
        "systems": list(systems) if systems else None,
        "start_utc": _day(start),
        "end_utc": _day(end),
        "columns": list(columns) if columns else None,
        "exclude": list(exclude),
        "rows": int(len(df)),
        "fingerprint": fingerprint(df, exclude=exclude),
        "source": source,
        "toolkit_version": __version__,
        "created_at": pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if extra:
        manifest.update(extra)
    return manifest


def write_manifest(manifest: dict[str, Any], path: str | Path) -> Path:
    """Write a manifest as indented JSON (atomically) and return its path."""
    out = Path(path)
    atomic_write(
        out,
        lambda tmp: tmp.write_text(
            json.dumps(manifest, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
        ),
    )
    return out


def read_manifest(path: str | Path) -> dict[str, Any]:
    """Read a manifest file, checking that it is one.

    Raises
    ------
    GBFSValidationError
        If the file is not JSON, or carries another ``format`` or no ``table``.
    """
    try:
        manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    except ValueError as exc:
        raise GBFSValidationError(f"{path} is not a JSON manifest: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("format") != MANIFEST_FORMAT:
        raise GBFSValidationError(f"{path} is not a {MANIFEST_FORMAT} manifest")
    check(bool(manifest.get("table")), f"{path}: the manifest names no table")
    return manifest


def verify_manifest(manifest: dict[str, Any], data: Any, *, strict: bool = True) -> dict[str, bool]:
    """Compare ``data`` with what ``manifest`` recorded: the row count and the fingerprint.

    Returns ``{"rows": bool, "fingerprint": bool}``. With ``strict`` (the default) any
    difference raises ``GBFSValidationError`` whose message names both values.

    Examples
    --------
    >>> import pandas as pd
    >>> df = pd.DataFrame({"x": [1, 2]})
    >>> m = create_manifest(df, table="t")
    >>> verify_manifest(m, df)
    {'rows': True, 'fingerprint': True}
    """
    df = _load(data)
    result = {"rows": True, "fingerprint": True}
    problems = []
    if manifest.get("rows") is not None and int(manifest["rows"]) != len(df):
        result["rows"] = False
        problems.append(f"{len(df)} rows instead of {manifest['rows']}")
    if manifest.get("fingerprint"):
        got = fingerprint(df, exclude=manifest.get("exclude") or ())
        if got != manifest["fingerprint"]:
            result["fingerprint"] = False
            problems.append(
                f"fingerprint {got[:19]}... instead of {manifest['fingerprint'][:19]}..."
            )
    if problems and strict:
        raise GBFSValidationError(
            f"the data differ from the manifest of {manifest.get('table')!r}: "
            + "; ".join(problems)
        )
    return result


def _selection_key(manifest: dict[str, Any]) -> str:
    select = {k: manifest.get(k) for k in ("table", "systems", "start_utc", "end_utc", "columns")}
    return hashlib.sha256(json.dumps(select, sort_keys=True).encode()).hexdigest()[:16]


def materialize(
    manifest: dict[str, Any] | str | Path,
    lake: str | Path | None = None,
    *,
    cache_dir: str | Path,
    reader: Callable[[dict[str, Any]], pd.DataFrame] | None = None,
    verify: bool = True,
    load: bool = False,
) -> Path | pd.DataFrame:
    """Read the data a manifest describes, check it, and keep a Parquet copy in ``cache_dir``.

    The rows are read from ``lake`` (a `gbfs_toolkit.store` lake, such as a release's
    ``data/<table>`` folder) restricted to the manifest's systems, days and columns, or from
    ``reader(manifest)`` if you pass one. With ``verify`` the copy must match the manifest's
    rows and fingerprint, or ``GBFSValidationError`` is raised and nothing is kept. A later call
    with the same manifest returns the cached copy without reading the lake again. The cache
    folder gets a ``.gitignore`` that ignores everything in it.

    Returns
    -------
    pathlib.Path or pandas.DataFrame
        The cached Parquet file, or the frame with ``load=True``.

    Raises
    ------
    ValueError
        If neither ``lake`` nor ``reader`` is given.
    """
    require_pyarrow("materialize")
    m = read_manifest(manifest) if isinstance(manifest, (str, Path)) else manifest
    if lake is None and reader is None:
        raise ValueError("materialize needs a lake folder or a reader")
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    ignore = cache / ".gitignore"
    if not ignore.exists():
        ignore.write_text(
            "# cache of gbfs_toolkit.repro.materialize: keep it out of git\n*\n", encoding="utf-8"
        )
    name = f"{m['table']}-{_selection_key(m)}"
    path, witness = cache / f"{name}.parquet", cache / f"{name}.verified"
    wanted = m.get("fingerprint")
    if path.exists() and (
        not verify or not wanted or (witness.exists() and witness.read_text().strip() == wanted)
    ):
        return pd.read_parquet(path) if load else path
    if reader is not None:
        df = reader(m)
    else:
        from gbfs_toolkit.store import read_lake

        end = m.get("end_utc")
        df = read_lake(
            lake,  # type: ignore[arg-type]
            systems=m.get("systems"),
            start=m.get("start_utc"),
            end=None if end is None else pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1),
            columns=m.get("columns"),
        )
    if verify:
        verify_manifest(m, df)
    atomic_write(path, lambda tmp: df.to_parquet(tmp, index=False, compression="zstd"))
    if wanted and verify:
        witness.write_text(wanted, encoding="utf-8")
    _log.info("materialized %s: %d rows -> %s", m["table"], len(df), path)
    return df if load else path


def export_sample(
    data: Any,
    out_dir: str | Path,
    *,
    table: str,
    stations: int = 5,
    station_col: str = "station_id",
    max_bytes: int = 5_000_000,
    time_col: str | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    """A small copy of a table for a CI run: ``stations`` stations, under ``max_bytes``.

    The first ``stations`` identifiers (sorted) are kept; the set is halved until the Parquet
    files fit in ``max_bytes``. The sample is written as a lake under
    ``<out_dir>/data/<table>/`` (so `materialize` and
    `gbfs_toolkit.store.read_lake` read it like the real one) next to a
    ``data_manifest.json`` that fingerprints the sample itself and lists its stations.

    Returns
    -------
    dict
        The manifest that was written.

    Raises
    ------
    GBFSValidationError
        If the table has no ``station_col`` column, or is empty.
    """
    from gbfs_toolkit.store import write_lake

    require_pyarrow("export_sample")
    df = _load(data)
    check(len(df) > 0, "export_sample: the table is empty")
    check(station_col in df.columns, f"export_sample: no {station_col!r} column to sample by")
    ids = sorted(df[station_col].astype(str).unique())
    keep = ids[: max(1, stations)]
    root = Path(out_dir)
    folder = root / "data" / table
    while True:
        if folder.exists():
            shutil.rmtree(folder)
        part = df[df[station_col].astype(str).isin(keep)]
        write_lake(part, folder, time_col=time_col)
        size = sum(f.stat().st_size for f in folder.rglob("*.parquet"))
        if size <= max_bytes or len(keep) <= 1:
            break
        keep = keep[: max(1, len(keep) // 2)]
    from gbfs_toolkit.store import read_lake

    sample = read_lake(folder)
    times = to_utc(
        part[time_col or ("observed_at_utc" if "observed_at_utc" in part else "fetched_at")]
    )
    manifest = create_manifest(
        sample,
        table=table,
        systems=sorted(part["system_id"].astype(str).unique())
        if "system_id" in part.columns
        else None,
        start=times.min(),
        end=times.max(),
        source=source,
        extra={"sample": True, "stations": keep, "bytes": int(size)},
    )
    write_manifest(manifest, root / MANIFEST_FILE)
    return manifest

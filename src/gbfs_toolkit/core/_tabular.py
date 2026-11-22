"""Internal: one way to read the table-like inputs of the large-volume code paths.

`aggregate`, `quality` and `store` accept, besides a pandas frame, an Arrow table (or dataset),
a DuckDB relation, or a path: a lake (``system_id=*/year=*/month=*``), a folder of Parquet
files, one file or a glob. This module turns any of them into a `Table` with the few things
those modules need: the column names, a row count, the time range, batches, a time window, and
a DuckDB relation when DuckDB is installed.

It is private (nothing here is public API): the public surface is the ``engine`` argument of
the functions that call it.
"""

from __future__ import annotations

import glob as _glob
import shutil
import tempfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pandas as pd

from gbfs_toolkit.core._common import require_pyarrow, to_utc

__all__ = [
    "ENGINES",
    "Table",
    "arrow_reader",
    "arrow_table",
    "has_duckdb",
    "is_pandas",
    "open_table",
    "relation_of",
    "require_duckdb",
    "resolve_engine",
    "sql_name",
    "sql_text",
]

#: Accepted values of the ``engine`` argument.
ENGINES: tuple[str, ...] = ("auto", "duckdb", "pandas")
_HIVE_TYPES = "{'system_id': VARCHAR, 'year': INTEGER, 'month': INTEGER}"


def has_duckdb() -> bool:
    """Whether the optional ``duckdb`` package can be imported."""
    try:
        import duckdb  # noqa: F401
    except ImportError:
        return False
    return True


def is_pandas(source: Any) -> bool:
    """Whether ``source`` is a pandas ``DataFrame``."""
    return isinstance(source, pd.DataFrame)


def require_duckdb(what: str) -> Any:
    """Import and return ``duckdb`` or raise an ``ImportError`` that names the extra."""
    try:
        import duckdb

        return duckdb
    except ImportError as e:
        raise ImportError(
            f"{what} needs duckdb. Install it with `pip install gbfs-toolkit[duckdb]`."
        ) from e


def arrow_table(rel: Any) -> Any:
    """A DuckDB relation as an Arrow table (the method is named differently across versions)."""
    fn = getattr(rel, "to_arrow_table", None) or rel.fetch_arrow_table
    return fn()


def arrow_reader(rel: Any, rows: int = 1_000_000) -> Any:
    """A DuckDB relation as a reader of Arrow record batches of about ``rows`` rows."""
    fn = getattr(rel, "to_arrow_reader", None) or rel.fetch_arrow_reader
    return fn(rows)


def sql_name(col: str) -> str:
    """A column name quoted for SQL."""
    return '"' + col.replace('"', '""') + '"'


def sql_text(text: str) -> str:
    """A string quoted as a SQL literal."""
    return "'" + text.replace("'", "''") + "'"


def resolve_engine(engine: str, source: Any, *, what: str = "This function") -> str:
    """``"duckdb"`` or ``"pandas"`` for ``engine`` and this kind of ``source``.

    ``"auto"`` keeps a pandas frame on pandas (the in-memory path, unchanged) and sends every
    other source to DuckDB when it is installed, to a chunked pandas computation otherwise.
    """
    if engine not in ENGINES:
        raise ValueError(f"engine must be one of {ENGINES}, got {engine!r}")
    if engine == "duckdb":
        require_duckdb(what)
        return "duckdb"
    if engine == "pandas":
        return "pandas"
    kind = source.kind if isinstance(source, Table) else ("pandas" if is_pandas(source) else "x")
    if kind == "pandas":
        return "pandas"
    return "duckdb" if has_duckdb() else "pandas"


class Table:
    """A table-like source, read lazily. See the module docstring."""

    kind = "table"

    def columns(self) -> list[str]:
        """Column names."""
        raise NotImplementedError

    def count(self) -> int:
        """Number of rows."""
        raise NotImplementedError

    def check_time(self, col: str) -> None:
        """Raise ``ValueError`` unless ``col`` exists and is a timestamp column."""
        raise NotImplementedError

    def time_range(self, col: str) -> tuple[pd.Timestamp, pd.Timestamp] | None:
        """Earliest and latest non-null time of ``col`` (UTC), or ``None`` for no value."""
        raise NotImplementedError

    def batches(self, columns: Sequence[str], rows: int = 1_000_000) -> Iterator[pd.DataFrame]:
        """The table, ``columns`` only, as pandas frames of about ``rows`` rows."""
        raise NotImplementedError

    def window(
        self, columns: Sequence[str], col: str, lo: pd.Timestamp, hi: pd.Timestamp
    ) -> pd.DataFrame:
        """Rows with ``lo <= col < hi``, ``columns`` only, as one pandas frame."""
        raise NotImplementedError

    def relation(self, con: Any = None) -> Any:
        """A DuckDB relation over the source (needs the ``duckdb`` extra)."""
        raise NotImplementedError

    def arrow(self, columns: Sequence[str] | None = None, where: str | None = None) -> Any:
        """The rows as one Arrow table; ``where`` is a SQL predicate (DuckDB only)."""
        raise NotImplementedError


class _PandasTable(Table):
    kind = "pandas"

    def __init__(self, df: pd.DataFrame) -> None:
        self.df = df

    def columns(self) -> list[str]:
        return [str(c) for c in self.df.columns]

    def count(self) -> int:
        return int(len(self.df))

    def check_time(self, col: str) -> None:
        if col not in self.df.columns:
            raise ValueError(f"time column {col!r} not found")

    def time_range(self, col: str) -> tuple[pd.Timestamp, pd.Timestamp] | None:
        t = to_utc(self.df[col], what=col).dropna()
        return (t.min(), t.max()) if len(t) else None

    def batches(self, columns: Sequence[str], rows: int = 1_000_000) -> Iterator[pd.DataFrame]:
        cols = [c for c in columns if c in self.df.columns]
        for i in range(0, max(len(self.df), 1), rows):
            yield self.df.iloc[i : i + rows][cols]

    def window(
        self, columns: Sequence[str], col: str, lo: pd.Timestamp, hi: pd.Timestamp
    ) -> pd.DataFrame:
        t = to_utc(self.df[col], what=col)
        mask = ((t >= lo) & (t < hi)).to_numpy()
        return self.df.loc[mask, [c for c in columns if c in self.df.columns]]

    def relation(self, con: Any = None) -> Any:
        duckdb = require_duckdb("A DuckDB relation")
        return (con or duckdb.connect()).from_df(self.df)

    def arrow(self, columns: Sequence[str] | None = None, where: str | None = None) -> Any:
        if where is not None:
            rel = self.relation().filter(where)
            if columns is not None:
                rel = rel.project(", ".join(sql_name(c) for c in columns))
            return arrow_table(rel)
        pa = require_pyarrow("An Arrow table")
        df = self.df if columns is None else self.df[list(columns)]
        return pa.Table.from_pandas(df, preserve_index=False)


def _timestamp_literal(ts: pd.Timestamp, arrow_type: Any) -> Any:
    import pyarrow as pa

    value = ts.tz_convert("UTC")
    if arrow_type.tz is None:
        return pa.scalar(value.tz_localize(None).to_pydatetime(), type=arrow_type)
    return pa.scalar(value.to_pydatetime(), type=arrow_type)


class _ArrowTable(Table):
    """An Arrow table or dataset (and, through `_PathTable`, a set of Parquet files)."""

    kind = "arrow"

    def __init__(self, data: Any) -> None:
        self._data = data  # pyarrow.Table or pyarrow.dataset.Dataset

    def _get(self) -> Any:
        return self._data

    @property
    def _is_dataset(self) -> bool:
        return hasattr(self._get(), "scanner")

    @property
    def _schema(self) -> Any:
        return self._get().schema

    def columns(self) -> list[str]:
        return list(self._schema.names)

    def count(self) -> int:
        data = self._get()
        return int(data.count_rows() if self._is_dataset else data.num_rows)

    def check_time(self, col: str) -> None:
        import pyarrow as pa

        if col not in self._schema.names:
            raise ValueError(f"time column {col!r} not found")
        kind = self._schema.field(col).type
        if not pa.types.is_timestamp(kind):
            raise ValueError(
                f"time column {col!r} is {kind}; a table, a dataset or a path needs a "
                "timestamp column (convert it first)"
            )

    def _select(self, columns: Sequence[str] | None, flt: Any = None) -> Any:
        data = self._get()
        cols = None if columns is None else [c for c in columns if c in self._schema.names]
        if self._is_dataset:
            return data.to_table(columns=cols, filter=flt)
        tbl = data if flt is None else data.filter(flt)
        return tbl if cols is None else tbl.select(cols)

    def time_range(self, col: str) -> tuple[pd.Timestamp, pd.Timestamp] | None:
        import pyarrow.compute as pc

        self.check_time(col)
        values = self._select([col])[col]
        mm = pc.min_max(values).as_py()
        if mm["min"] is None:
            return None
        lo, hi = pd.Timestamp(mm["min"]), pd.Timestamp(mm["max"])
        if lo.tzinfo is None:
            lo, hi = lo.tz_localize("UTC"), hi.tz_localize("UTC")
        return lo.tz_convert("UTC"), hi.tz_convert("UTC")

    def batches(self, columns: Sequence[str], rows: int = 1_000_000) -> Iterator[pd.DataFrame]:
        cols = [c for c in columns if c in self._schema.names]
        data = self._get()
        if self._is_dataset:
            for b in data.to_batches(columns=cols, batch_size=rows):
                yield b.to_pandas()
        else:
            for b in data.select(cols).to_batches(max_chunksize=rows):
                yield b.to_pandas()

    def window(
        self, columns: Sequence[str], col: str, lo: pd.Timestamp, hi: pd.Timestamp
    ) -> pd.DataFrame:
        import pyarrow.dataset as ds

        self.check_time(col)
        kind = self._schema.field(col).type
        flt = (ds.field(col) >= _timestamp_literal(lo, kind)) & (
            ds.field(col) < _timestamp_literal(hi, kind)
        )
        return self._select(columns, flt).to_pandas()

    def relation(self, con: Any = None) -> Any:
        duckdb = require_duckdb("A DuckDB relation")
        return (con or duckdb.connect()).from_arrow(self._get())

    def arrow(self, columns: Sequence[str] | None = None, where: str | None = None) -> Any:
        if where is not None:
            rel = self.relation().filter(where)
            if columns is not None:
                rel = rel.project(", ".join(sql_name(c) for c in columns))
            return arrow_table(rel)
        return self._select(columns)


class _PathTable(_ArrowTable):
    """Parquet files: a lake, a folder, one file or a glob."""

    kind = "path"

    def __init__(self, files: list[str], *, lake: bool, root: str | None) -> None:
        super().__init__(None)
        self.files = files
        self.lake = lake
        self.root = root

    def _get(self) -> Any:
        if self._data is None:
            require_pyarrow("A path source")
            import pyarrow as pa
            import pyarrow.dataset as ds

            if self.lake:
                schema = pa.schema(
                    [("system_id", pa.string()), ("year", pa.int32()), ("month", pa.int32())]
                )
                self._data = ds.dataset(
                    self.files,
                    format="parquet",
                    partitioning=ds.partitioning(schema, flavor="hive"),
                    partition_base_dir=self.root,
                )
            else:
                self._data = ds.dataset(self.files, format="parquet")
        return self._data

    def relation(self, con: Any = None) -> Any:
        duckdb = require_duckdb("A DuckDB relation")
        con = con or duckdb.connect()
        files = [str(f) for f in self.files]
        if self.lake:
            return con.sql(
                f"SELECT * FROM read_parquet({files!r}, hive_partitioning = true, "
                f"union_by_name = true, hive_types = {_HIVE_TYPES})"
            )
        return con.sql(f"SELECT * FROM read_parquet({files!r}, union_by_name = true)")

    def count(self) -> int:
        if has_duckdb():
            return int(self.relation().aggregate("count(*)").fetchall()[0][0])
        return super().count()


class _RelationTable(Table):
    kind = "relation"

    def __init__(self, rel: Any) -> None:
        self.rel = rel

    def columns(self) -> list[str]:
        return [str(c) for c in self.rel.columns]

    def count(self) -> int:
        return int(self.rel.aggregate("count(*)").fetchall()[0][0])

    def check_time(self, col: str) -> None:
        names = self.columns()
        if col not in names:
            raise ValueError(f"time column {col!r} not found")
        kind = str(self.rel.types[names.index(col)])
        if not kind.startswith("TIMESTAMP"):
            raise ValueError(
                f"time column {col!r} is {kind}; a relation needs a TIMESTAMP column (cast it first)"
            )

    def time_range(self, col: str) -> tuple[pd.Timestamp, pd.Timestamp] | None:
        self.check_time(col)
        c = sql_name(col)
        lo, hi = self.rel.aggregate(f"min(epoch_us({c})), max(epoch_us({c}))").fetchall()[0]
        if lo is None:
            return None
        return pd.to_datetime(lo, unit="us", utc=True), pd.to_datetime(hi, unit="us", utc=True)

    def batches(self, columns: Sequence[str], rows: int = 1_000_000) -> Iterator[pd.DataFrame]:
        cols = [c for c in columns if c in self.columns()]
        reader = arrow_reader(self.rel.project(", ".join(sql_name(c) for c in cols)), rows)
        for b in reader:
            yield b.to_pandas()

    def window(
        self, columns: Sequence[str], col: str, lo: pd.Timestamp, hi: pd.Timestamp
    ) -> pd.DataFrame:
        cols = [c for c in columns if c in self.columns()]
        c = sql_name(col)
        lo_us, hi_us = int(lo.value // 1000), int(hi.value // 1000)
        return (
            self.rel.filter(f"epoch_us({c}) >= {lo_us} AND epoch_us({c}) < {hi_us}")
            .project(", ".join(sql_name(x) for x in cols))
            .df()
        )

    def relation(self, con: Any = None) -> Any:
        return self.rel

    def arrow(self, columns: Sequence[str] | None = None, where: str | None = None) -> Any:
        rel = self.rel
        if where is not None:
            rel = rel.filter(where)
        if columns is not None:
            rel = rel.project(", ".join(sql_name(c) for c in columns))
        return arrow_table(rel)


def _parquet_files(path: str) -> tuple[list[str], bool, str | None]:
    """Files under ``path`` (a lake, a folder, a file or a glob), and whether it is a lake."""
    p = Path(path)
    if p.is_dir():
        lake = sorted(str(f) for f in p.glob("system_id=*/year=*/month=*/*.parquet"))
        if lake:
            return lake, True, str(p)
        files = sorted(
            str(f) for f in p.rglob("*.parquet") if not any(x.startswith(".") for x in f.parts)
        )
        return files, False, None
    if p.is_file():
        return [str(p)], False, None
    return sorted(_glob.glob(path, recursive=True)), False, None


def open_table(source: Any, *, what: str = "This function") -> Table:
    """Wrap a pandas frame, Arrow table or dataset, DuckDB relation or path as a `Table`.

    Raises
    ------
    TypeError
        For anything else.
    FileNotFoundError
        For a path with no Parquet file.
    """
    if isinstance(source, Table):
        return source
    if is_pandas(source):
        return _PandasTable(source)
    if isinstance(source, (str, Path)):
        files, lake, root = _parquet_files(str(source))
        if not files:
            raise FileNotFoundError(f"{what}: no Parquet file under {source}")
        return _PathTable(files, lake=lake, root=root)
    module = type(source).__module__
    if module.startswith("pyarrow"):
        import pyarrow as pa
        import pyarrow.dataset as ds

        if isinstance(source, (pa.Table, ds.Dataset)):
            return _ArrowTable(source)
        if isinstance(source, pa.RecordBatch):
            return _ArrowTable(pa.Table.from_batches([source]))
    if module.startswith("duckdb"):
        return _RelationTable(source)
    raise TypeError(
        f"{what}: expected a pandas DataFrame, an Arrow table, a DuckDB relation or a path, "
        f"got {type(source).__name__}"
    )


@contextmanager
def relation_of(table: Table) -> Iterator[Any]:
    """A DuckDB relation over ``table``, on a private connection that is closed afterwards.

    A relation the caller built is used as it is. Otherwise the connection reads time as UTC
    and spills to a temporary folder that is removed, never to the working directory.
    """
    if isinstance(table, _RelationTable):
        yield table.rel
        return
    duckdb = require_duckdb("engine='duckdb'")
    tmp = tempfile.mkdtemp(prefix="gbfs-duckdb-")
    con = duckdb.connect(config={"temp_directory": tmp})
    try:
        con.execute("SET TimeZone = 'UTC'")
        yield table.relation(con)
    finally:
        con.close()
        shutil.rmtree(tmp, ignore_errors=True)

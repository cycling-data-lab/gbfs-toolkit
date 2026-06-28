# Contributing

Thanks for your interest. `gbfs-toolkit` is a focused, research-grade library; contributions
that keep it that way are very welcome.

## Setup

```bash
pip install -e ".[dev]"
pytest -q                       # 137 tests
ruff check . && ruff format --check .
```

## Scope

The library is deliberately bounded. In scope: ingesting/normalising GBFS, semantic & dynamic
quality audit, longitudinal panels, descriptive statistics, geospatial joins. **Out of scope**
(by design, see [`METHODOLOGY.md`](https://github.com/cycling-data-lab/gbfs-toolkit/blob/main/METHODOLOGY.md)): routing/isochrones, OD/trip inference,
demand prediction or imputation, schedulers/daemons, and interactive visualisation. The library
returns tidy `DataFrame`/`GeoDataFrame`; you bring the model and the map.

## Conventions

- **Pure functions on canonical frames** (mirrored as `.gbfs` accessor methods). No hidden global
  state. Validate inputs with `require_columns` so a bad frame raises a clear `SchemaError`.
- **Tz-aware UTC** timestamps and **nullable dtypes** everywhere; never silently impute.
- Optional dependencies stay behind extras and lazy imports, so the core is numpy/scipy/pandas only.
- New behaviour needs a test; keep coverage ≥ 85% (CI enforces it). Run `ruff` before pushing.
- Document any methodological assumption or threshold in `METHODOLOGY.md`.

## Docstring standard

Docstrings are the API reference: `mkdocstrings` renders them on the site, `pytest
--doctest-modules` runs their examples, and `interrogate` (fail-under 90) gates
coverage. Every public function uses **NumPy style** with this section order, and
only the sections it needs:

1. **Summary line** — one imperative sentence, ≤ 90 characters, on the first line.
2. **Extended description** — the *why*: the research question it answers, the
   pitfall it avoids, the scope boundary. This "why first" paragraph is the house
   style; it is what makes the reference read like documentation, not a signature dump.
3. **Parameters** — every argument, with type and meaning.
4. **Returns** — type and shape (name the columns / index of a returned frame).
5. **Raises** — when the function validates and rejects input.
6. **Examples** — required on any public function that takes a business frame
   (info / status / panel / GeoDataFrame) and returns a frame, a Series, or changes
   state. Make it **self-contained and deterministic**: build a 2–20 row frame
   inline (never load a dataset), add `# doctest: +NORMALIZE_WHITESPACE` for any
   DataFrame output, and wrap numeric returns in `float(...)` / `round(...)` or test
   a stable property — never assert a raw float (it prints as `np.float64(...)`).
7. **References** — the canonical paper for any non-trivial algorithm.

Exempt from the Examples rule: internal helpers, trivial property accessors, pure
utilities, and network functions (`fetch*`, `systems_catalog`).

Worked examples that need more than one function, real data, or a figure are
**not** docstrings: a task-oriented pipeline is a runnable script under `examples/`,
included into a How-To page with the `--8<--` snippet syntax (one source of truth,
linted and run), and an end-to-end narrative is a notebook executed by `nbmake`.

## Reporting issues

Please separate two distinct kinds of report:

- **Software defects** (a crash, a wrong result, a packaging problem) belong in the
  [issue tracker](https://github.com/cycling-data-lab/gbfs-toolkit/issues). Include `show_versions()`
  output and a minimal reproducer.
- **Methodological disputes** (a station you believe the A1–A7 audit flags or misses incorrectly)
  concern the taxonomy itself, which is defined by the companion dataset
  [`gbfs-audit-catalogue`](https://github.com/cycling-data-lab/gbfs-audit-catalogue). Raise those
  there, with the feed and station, so the operational definition and the implementation stay in
  step.

## Pull requests

Keep PRs focused, describe the *why*, and update `CHANGELOG.md`. If a change is breaking, say so
and provide the migration.

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
(by design — see [`METHODOLOGY.md`](./METHODOLOGY.md)): routing/isochrones, OD/trip inference,
demand prediction or imputation, schedulers/daemons, and interactive visualisation. The library
returns tidy `DataFrame`/`GeoDataFrame`; you bring the model and the map.

## Conventions

- **Pure functions on canonical frames** (mirrored as `.gbfs` accessor methods). No hidden global
  state. Validate inputs with `require_columns` so a bad frame raises a clear `SchemaError`.
- **Tz-aware UTC** timestamps and **nullable dtypes** everywhere; never silently impute.
- Optional dependencies stay behind extras and lazy imports — the core is numpy/scipy/pandas only.
- New behaviour needs a test; keep coverage ≥ 85% (CI enforces it). Run `ruff` before pushing.
- Document any methodological assumption or threshold in `METHODOLOGY.md`.

## Pull requests

Keep PRs focused, describe the *why*, and update `CHANGELOG.md`. If a change is breaking, say so
and provide the migration.

<!-- Thanks for contributing to gbfs-toolkit. -->

## What and why

<!-- What does this change do, and why? Link any related issue (e.g. "Closes #12"). -->

## Checklist

- [ ] The change stays within scope (descriptive only: no OD/trip inference, routing, prediction or imputation).
- [ ] New behaviour has a test; `pytest -q` passes.
- [ ] `ruff check .` and `ruff format --check .` pass.
- [ ] Public functions stay pure on canonical frames (tz-aware UTC, nullable dtypes); no hidden global state.
- [ ] Any methodological assumption or threshold is documented in `METHODOLOGY.md`.
- [ ] `CHANGELOG.md` is updated for user-facing changes.

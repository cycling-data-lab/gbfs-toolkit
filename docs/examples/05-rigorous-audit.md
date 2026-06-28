# Rigorous & comparative analysis

The two analyses a reviewer leans on hardest: showing the audit's verdicts are not
knife-edge, and turning the clean stations into defensible research metrics. Both
parts are self-contained (bundled data plus small synthetic frames, no network) and
run in CI.

## Part 1 — Audit robustness and uncertainty

Report the A1–A7 audit the way a careful study should: not just the verdict, but
evidence that it survives the threshold choices.

- Verdict and capacity convention
  ([`audit_static`][gbfs_toolkit.audit_static],
  [`capacity_convention`][gbfs_toolkit.capacity_convention]).
- Threshold robustness with
  [`audit_sensitivity`][gbfs_toolkit.audit_sensitivity] — the Jaccard overlap of the
  flagged set across a grid, so you can claim a stability plateau.
- Seeded cluster-bootstrap intervals on every flag rate with
  [`flag_rate_ci`][gbfs_toolkit.flag_rate_ci].
- Spatial hotspots controlled for multiple testing:
  [`local_morans_i`][gbfs_toolkit.local_morans_i] with `fdr=True`
  (Benjamini–Hochberg).

```console
$ python examples/05_rigorous_audit.py
```

```python
--8<-- "examples/05_rigorous_audit.py"
```

## Part 2 — Equity, accessibility and rebalancing

Three downstream questions, and the signature rebalancing metric.

- Equity with [`theil_index`][gbfs_toolkit.theil_index] (between/within-zone) and
  [`palma_ratio`][gbfs_toolkit.palma_ratio].
- Accessibility under distance decay with
  [`two_step_fca`][gbfs_toolkit.two_step_fca] (E2SFCA).
- Spatial fragmentation of the live fleet with
  [`rebalancing_tension`][gbfs_toolkit.rebalancing_tension] (Wasserstein earth-mover
  distance, purely descriptive), plus
  [`censored_time_ratio`][gbfs_toolkit.censored_time_ratio] and an honest interval
  for autocorrelated series ([`block_bootstrap_ci`][gbfs_toolkit.block_bootstrap_ci],
  [`effective_sample_size`][gbfs_toolkit.effective_sample_size]).

```console
$ python examples/06_equity_rebalancing.py
```

```python
--8<-- "examples/06_equity_rebalancing.py"
```

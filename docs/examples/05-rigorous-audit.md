# A rigorous, reproducible audit

How to report an audit the way a careful study should: not just the A1–A7
verdict, but evidence that the conclusion is not knife-edge. This scenario
chains four steps on the bundled example dataset, with no network access, so it
runs anywhere and is exercised in CI.

1. **Verdict and convention.** [`audit_static`][gbfs_toolkit.audit_static] gives
   the per-station flags; [`capacity_convention`][gbfs_toolkit.capacity_convention]
   labels how the `capacity` field is published.
2. **Threshold robustness.** [`audit_sensitivity`][gbfs_toolkit.audit_sensitivity]
   sweeps a threshold and reports the Jaccard overlap of the flagged set against
   the baseline, so you can claim a stability plateau rather than a lucky cut-off.
3. **Uncertainty.** [`flag_rate_ci`][gbfs_toolkit.flag_rate_ci] puts a seeded
   cluster-bootstrap 95% interval on every flag rate.
4. **Spatial hotspots, controlled.** [`local_morans_i`][gbfs_toolkit.local_morans_i]
   with `fdr=True` applies a Benjamini–Hochberg false-discovery-rate correction,
   the standard fix for running one test per station.

Run it:

```console
$ python examples/05_rigorous_audit.py
```

Full source (the single source of truth, linted and run in CI):

```python
--8<-- "examples/05_rigorous_audit.py"
```

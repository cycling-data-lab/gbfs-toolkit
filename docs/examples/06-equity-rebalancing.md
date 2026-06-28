# Equity, accessibility and rebalancing tension

Three questions a transport-geography study asks of a shared-mobility system, and
the one signature metric that sets this library apart. Self-contained (bundled
data plus small synthetic frames, no network), run in CI.

1. **How fairly is supply shared?** [`theil_index`][gbfs_toolkit.theil_index]
   decomposes inequality into a *between-zone* term (centre versus periphery) and
   a *within-zone* term, and [`palma_ratio`][gbfs_toolkit.palma_ratio] measures
   the extremes the Gini smooths over.
2. **How reachable is it?** [`two_step_fca`][gbfs_toolkit.two_step_fca] with a
   Gaussian distance decay is the enhanced 2SFCA (E2SFCA) accessibility, against
   your own demand points (bring-your-own-data).
3. **How spatially fragmented is the live fleet?**
   [`rebalancing_tension`][gbfs_toolkit.rebalancing_tension] is the minimum
   bikes × kilometres of relocation to reach a target distribution, via the
   Wasserstein earth-mover distance — a purely descriptive scalar of spatial
   tension, with no trip inference.
   [`censored_time_ratio`][gbfs_toolkit.censored_time_ratio] reports the demand
   signal lost at saturation, and
   [`block_bootstrap_ci`][gbfs_toolkit.block_bootstrap_ci] /
   [`effective_sample_size`][gbfs_toolkit.effective_sample_size] give honest
   uncertainty for the autocorrelated series.

Run it:

```console
$ python examples/06_equity_rebalancing.py
```

Full source:

```python
--8<-- "examples/06_equity_rebalancing.py"
```

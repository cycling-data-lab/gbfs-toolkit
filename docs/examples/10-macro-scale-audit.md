# Compare systems at macro scale

Are the data-quality anomalies you see in one feed local bugs, or global
architecture choices of an operator? This is the only scenario that shows the
library's *scale*: filter the world catalogue to a country, audit every reachable
feed with one call, and rank the A1–A7 classes by how widely they fire.

!!! warning "Live scenario"
    This one is **not** self-contained: it downloads the MobilityData catalogue and
    fetches each feed, so it needs `[fetch]` and a network connection. Treat the
    numbers as a dated snapshot.

What the script does:

- Loads the world inventory with [`systems_catalog`][gbfs_toolkit.systems_catalog]
  and narrows it with [`filter_catalog`][gbfs_toolkit.filter_catalog] (by country,
  city or name).
- Fetches and audits every selected system in one call with
  [`audit_catalogue`][gbfs_toolkit.audit_catalogue], which returns the per-station
  verdict and a per-system status so dead feeds are accounted for, not hidden.
- Aggregates to per-system flags and ranks the classes by incidence across the corpus.

Run it:

```console
$ python examples/10_macro_scale_audit.py --country FR --limit 25
```

Full source:

```python
--8<-- "examples/10_macro_scale_audit.py"
```

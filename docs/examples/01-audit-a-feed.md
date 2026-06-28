# Audit a feed

First contact with an unknown feed: see what is in it, and decide what can be
trusted. Most operator feeds have *something* wrong — a block of stations at
(0, 0), a placeholder capacity copied across the whole network, car-share parking
dressed up as bike-share. Catch the damage before it leaks into a model.

!!! info "Requirements"
    Extras: `[fetch]`. Input: a `gbfs.json` discovery URL. The static audit also
    runs offline on the bundled sample: `info, _ = gb.load_example()`.

What the script does:

- Resolves the discovery document once and prints the feed's health summary.
- Runs the A1–A7 static audit with
  [`audit_static`][gbfs_toolkit.audit_static] and reports the flagged stations.
- Adds the live-availability checks (D1–D3) with
  [`audit_dynamic`][gbfs_toolkit.audit_dynamic].
- Keeps only the trustworthy stations for downstream analysis.

Run it:

```console
$ python examples/01_audit_a_feed.py https://example.com/gbfs.json --system-id mycity
```

Full source (the single source of truth, linted and runnable):

```python
--8<-- "examples/01_audit_a_feed.py"
```

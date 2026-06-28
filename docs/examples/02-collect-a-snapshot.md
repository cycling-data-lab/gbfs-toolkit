# Collect a snapshot

One collection run, meant to be driven by cron rather than a loop. The toolkit
collects; your orchestrator decides when. Poll `station_status` every few minutes
for a few weeks and you have a panel to analyse.

!!! info "Requirements"
    Extras: `[fetch]`, `[parquet]`. A writable directory for the lake.

What the script does:

- Opens a polite session ([`build_session`][gbfs_toolkit.build_session]) and
  fetches `station_status`, sending the stored ETag so an unchanged feed is skipped.
- Normalises the payload with
  [`to_canonical_station_status`][gbfs_toolkit.to_canonical_station_status].
- Appends it to a Hive-partitioned Parquet lake with
  [`append_to_parquet`][gbfs_toolkit.append_to_parquet] and remembers the new ETag.

Schedule it (every two minutes):

```cron
*/2 * * * * python examples/02_collect_snapshot.py velib /data/velib_lake
```

Full source:

```python
--8<-- "examples/02_collect_snapshot.py"
```

## Freezing a citable snapshot

When a study deposits the lake it collected, record its provenance so reviewers can
verify the data were frozen as described.
[`generate_manifest`][gbfs_toolkit.generate_manifest] writes a cryptographic
manifest — a SHA-256 per Parquet partition plus a system/date summary — that you
archive alongside the data (e.g. on Zenodo):

```python
import gbfs_toolkit as gb

manifest = gb.generate_manifest("velib_lake/")  # {sha256 per partition, totals, dates}
```

It hashes what was written; it never alters the lake.

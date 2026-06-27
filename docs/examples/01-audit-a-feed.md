# Audit a feed

First contact with an unknown feed: see what is in it, and decide what can be trusted. Most
operator feeds have something wrong with them, for example a block of stations at coordinates
(0, 0), a placeholder capacity copied across the whole network, or car-share parking presented as
bike-share. The goal is to see that damage before it leaks into a model.

!!! info "Requirements"
    Extras: `[fetch]`. Input: a `gbfs.json` discovery URL.

!!! tip "Try it offline"
    No feed at hand? The same static audit runs on the bundled sample with no network access:
    `info, _ = gb.load_example(); gb.audit_static(info)`.

## Walkthrough

### 1. Discover the feed and read its summary

`GBFSFeed.from_url` resolves the discovery document once, then exposes each endpoint on demand.
The summary is a one-glance card: station and vehicle counts, the GBFS version, and data
staleness.

```python
import gbfs_toolkit as gb

feed = gb.GBFSFeed.from_url(gbfs_url, system_id="mycity")
print(feed.summary())
```

### 2. Run the static audit (A1–A7)

`audit_static` returns one row per station, with a boolean for each rule, a `flagged` column, and
a human-readable `reason`. The thresholds are the published ones, documented in the
[Methodology](../methodology.md).

```python
stations = feed.station_information()
verdict = gb.audit_static(stations)
```

### 3. See which problems occur, and how often

```python
flagged = verdict[verdict["flagged"]]
print(f"{len(flagged)} of {len(verdict)} stations flagged")
print(flagged["reason"].value_counts().to_string())
```

### 4. Keep the analysable subset

This clean frame is what every downstream step should use.

```python
clean = stations[~verdict["flagged"].to_numpy()].reset_index(drop=True)
```

### 5. If the feed is live, add the dynamic checks (D1–D3)

The dynamic audit catches negative counts, structural over-capacity, and staleness on a live
availability snapshot.

```python
if feed.has("station_status"):
    dyn = gb.audit_dynamic(feed.availability(), ttl_seconds=feed.ttl)
```

## Run it

```bash
python 01_audit_a_feed.py https://example.com/gbfs.json --system-id mycity
```

## Illustrative output

The exact figures depend on the feed.

```text
system mycity  GBFS 2.3  412 stations  0 vehicles  fetched 4s ago

23 of 412 stations flagged

A4 geospatial outlier       14
A6 zero-capacity dock        9

389 stations kept for analysis
2 stations with live-data problems (D3 stale)
```

## Interpreting the output

- A high flagged fraction is itself a finding. Read the [Methodology](../methodology.md) before modelling such a feed.
- **A4 (geospatial outlier)** usually means transposed coordinates or a distant depot listed as a station. Inspect those positions before trusting any spatial analysis.
- **A6 (zero-capacity dock)** suggests the operator left capacity unset, so any capacity-weighted metric will be biased low.
- The `reason` column explains every verdict in words, so a flagged station can be triaged rather than dropped blindly.

## Related

- API: `audit_static`, `audit_dynamic`, `drop_flagged` ([Static audit](../api.md#static-semantic-audit-a1a7), [Dynamic audit](../api.md#dynamic-audit-d1d3)).
- Concepts: the [A1–A7 thresholds](../methodology.md) and the [AuditVerdict contract](../data-model.md#auditverdict).

## Full script

```python title="examples/01_audit_a_feed.py"
--8<-- "examples/01_audit_a_feed.py"
```

<div class="hero" markdown>

# gbfs-toolkit

<p class="subtitle">Research-grade ingestion and semantic quality audit for GBFS bike-share feeds.</p>

<p class="authors">Rohan Fossé<sup>1</sup> and Gaël Pallares<sup>2</sup></p>
<p class="affiliation"><sup>1</sup> CESI Engineering School, Montpellier &nbsp;·&nbsp; <sup>2</sup> CESI LINEACT (EA 7527), Montpellier, France</p>

<p class="badges">
<a href="https://pypi.org/project/gbfs-toolkit/"><img alt="PyPI" src="https://img.shields.io/pypi/v/gbfs-toolkit?color=0d7d77&label=PyPI"></a>
<a href="https://pypi.org/project/gbfs-toolkit/"><img alt="Python" src="https://img.shields.io/pypi/pyversions/gbfs-toolkit?color=0d7d77"></a>
<a href="https://github.com/cycling-data-lab/gbfs-toolkit/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/cycling-data-lab/gbfs-toolkit/actions/workflows/ci.yml/badge.svg"></a>
<a href="https://github.com/cycling-data-lab/gbfs-toolkit/blob/main/LICENSE"><img alt="License" src="https://img.shields.io/badge/License-MIT-0d7d77"></a>
</p>

<p class="keywords">
<span class="kw">GBFS</span>
<span class="kw">bike-sharing</span>
<span class="kw">shared mobility</span>
<span class="kw">data quality</span>
<span class="kw">semantic validation</span>
<span class="kw">reproducibility</span>
<span class="kw">open data</span>
</p>

</div>

!!! abstract
    `gbfs-toolkit` ingests GBFS bike-share feeds into a stable, version-independent data model and
    audits their semantic quality with the A1–A7 taxonomy of Fossé and Pallares. MobilityData's
    [`gbfs-validator`](https://github.com/MobilityData/gbfs-validator) checks that a feed is
    *syntactically* valid. This toolkit checks whether it is *semantically* trustworthy and
    analysis-ready, which is the part a study actually depends on. It consolidates ingestion,
    cross-version normalisation, and the published quality-audit pipeline into one tested,
    installable interface for reuse across shared-mobility research.

<div class="grid cards" markdown>

-   :material-download:{ .lg .middle } __Getting started__

    ---

    Install the core and only the extras you need, then audit a feed in a few lines.

    [:octicons-arrow-right-24: Installation and quickstart](getting-started.md)

-   :material-shield-check:{ .lg .middle } __Semantic audit__

    ---

    The published static taxonomy (A1–A7) and the dynamic checks (D1–D3), with every threshold stated.

    [:octicons-arrow-right-24: Methodology](methodology.md)

-   :material-api:{ .lg .middle } __API reference__

    ---

    Every public function, grouped by module and generated from the source docstrings.

    [:octicons-arrow-right-24: Reference](api.md)

-   :material-format-quote-close:{ .lg .middle } __Cite this work__

    ---

    BibTeX, ORCID identifiers, and provenance tooling for reproducible studies.

    [:octicons-arrow-right-24: Citing this work](citing.md)

</div>

## Position in the GBFS ecosystem

`gbfs-toolkit` is the semantic counterpart to the syntactic validator, not a replacement for it.
The two operate at different layers and answer different questions.

| Aspect | `gbfs-validator` (MobilityData) | `gbfs-toolkit` (CESI LINEACT) |
|---|---|---|
| Validation layer | Syntactic: JSON-schema conformance | Semantic: analysis-readiness and plausibility |
| Question answered | Is the feed well-formed GBFS? | Can I trust each station for a study? |
| Granularity | Feed and file | Per-station verdict (A1–A7) and per-snapshot verdict (D1–D3) |
| Cross-version model | Not applicable | Canonical frames across GBFS 1.x, 2.x and 3.x |
| Spatial and temporal checks | None | Coordinates, perimeter, staleness, frozen sensors |
| Output | Pass or fail with schema errors | Tidy `DataFrame` of verdicts with explicit reasons |
| Scope | Conformance | Ingestion, audit, and longitudinal analysis |

A feed can pass the syntactic validator and still carry placeholder capacities, phantom docks,
transposed coordinates, or out-of-perimeter stations. Those are the defects the semantic audit is
designed to surface.

## Scope and limitations

!!! warning "What the toolkit does not do"
    `gbfs-toolkit` ingests, normalises, audits and summarises GBFS feeds. It deliberately does
    **not** perform origin-destination or trip inference, routing or isochrones, demand
    prediction, or imputation of missing data, and it ships no scheduler or daemon. Flow
    quantities are observed lower bounds, not trip counts (see the [Methodology](methodology.md)).
    These boundaries are by design: the toolkit returns tidy frames, and you bring the model and
    the map.

## Install

```bash
pip install gbfs-toolkit
```

The core depends only on numpy, scipy and pandas. Optional capabilities live behind extras
(`[fetch]`, `[parquet]`, `[cluster]`, `[geo]`, `[osm]`, `[dtw]`). See
[Getting started](getting-started.md) for the full extras matrix.

## Quickstart

```python
import gbfs_toolkit as gb

info, status = gb.load_example()      # bundled sample, no network needed
clean = info.gbfs.drop_flagged()      # audit A1–A7 and keep the trustworthy stations
av = info.gbfs.join_status(status)    # availability frame
av.gbfs.occupancy()                   # bikes / (bikes + docks), NaN-safe
```

## The same audit on a live network

Run against a live Vélib' Métropole feed (Paris), `audit_static` flags a small, explainable
fraction of a real 1500-station network:

```text
system_id                velib
gbfs_version             2.x
total_stations           1517
total_bikes_available    17063
feed_staleness_min       25.1

31 of 1517 stations flagged
Geospatial error            26
Structural over-capacity     5
```

The 26 geospatial outliers (A4) and 5 free-floating anchors (A3) are exactly the cases a study
should inspect before trusting station coordinates or capacities. The exact figures vary with each
live snapshot.

## Citation and licence

If you use `gbfs-toolkit` in a publication, please cite it and the accompanying dataset paper.
See [Citing this work](citing.md). Released under the [MIT License](https://github.com/cycling-data-lab/gbfs-toolkit/blob/main/LICENSE).
Affiliated with [CESI LINEACT (EA 7527)](https://lineact.cesi.fr), Montpellier, France.

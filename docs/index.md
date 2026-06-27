# gbfs-toolkit

Research-grade ingestion and semantic quality audit for GBFS bike-share feeds.

MobilityData's [`gbfs-validator`](https://github.com/MobilityData/gbfs-validator) checks that a
feed is *syntactically* valid. `gbfs-toolkit` checks whether it is *semantically* trustworthy and
analysis-ready, using the published A1–A7 quality taxonomy of Fossé and Pallares, and normalises
feeds into a stable, version-independent data model that can be reused across studies.

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

## Citation and licence

If you use `gbfs-toolkit` in a publication, please cite it and the accompanying dataset paper.
See [Citing this work](citing.md). Released under the [MIT License](https://github.com/cycling-data-lab/gbfs-toolkit/blob/main/LICENSE).
Affiliated with [CESI LINEACT (EA 7527)](https://lineact.cesi.fr), Montpellier, France.

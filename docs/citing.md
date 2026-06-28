# Citing this work

If you use `gbfs-toolkit` in a publication, please cite both the software and the accompanying
dataset paper. Citing software explicitly supports reproducibility and gives credit to the
research-software effort behind the toolkit.

The machine-readable metadata is maintained in
[`CITATION.cff`](https://github.com/cycling-data-lab/gbfs-toolkit/blob/main/CITATION.cff), which
GitHub renders as a "Cite this repository" panel and which reference managers can import directly.

## Software

```bibtex
@software{fosse_gbfs_toolkit_2026,
  author    = {Fossé, Rohan and Pallares, Gaël},
  title     = {{gbfs-toolkit: research-grade ingestion and semantic
               quality audit for GBFS feeds}},
  year      = {2026},
  version   = {1.4.0},
  doi       = {10.5281/zenodo.20992153},
  license   = {MIT},
  url       = {https://github.com/cycling-data-lab/gbfs-toolkit},
  note      = {ORCID: 0009-0002-2195-0198, 0009-0002-8680-604X}
}
```

Cite the exact version you used. The canonical schema and public API are frozen under semantic
versioning, so reporting the version is sufficient to identify the behaviour your study relied on.

## Dataset paper

The A1–A7 semantic taxonomy implemented here comes from the `gbfs-audit-catalogue` dataset paper.

```bibtex
@article{fosse_gbfs_catalogue_2026,
  author  = {Fossé, Rohan and Pallares, Gaël},
  title   = {{A certified, anomaly-flagged reference catalogue for
             GBFS bike-sharing feeds}},
  year    = {2026},
  note    = {gbfs-audit-catalogue dataset paper, in preparation}
}
```

The validation data behind the taxonomy live in the companion repository
[`gbfs-audit-catalogue`](https://github.com/cycling-data-lab/gbfs-audit-catalogue), so the audit
rules rest on a verifiable corpus rather than on assertion.

## Authors

| Author | ORCID | Affiliation |
|---|---|---|
| Rohan Fossé | [0009-0002-2195-0198](https://orcid.org/0009-0002-2195-0198) | CESI Engineering School, Montpellier, France |
| Gaël Pallares | [0009-0002-8680-604X](https://orcid.org/0009-0002-8680-604X) | CESI LINEACT (EA 7527), Montpellier, France |

## Archival DOI

Each tagged GitHub release is archived on Zenodo with a citable DOI, minted automatically from the
[`.zenodo.json`](https://github.com/cycling-data-lab/gbfs-toolkit/blob/main/.zenodo.json) metadata
(authorship, ORCID identifiers, licence).

- **Concept DOI** (resolves to the latest version, use this in a paper):
  [10.5281/zenodo.20992153](https://doi.org/10.5281/zenodo.20992153)
- **Version DOI** for v1.4.0 (the exact archived snapshot):
  [10.5281/zenodo.20992154](https://doi.org/10.5281/zenodo.20992154)

Cite the concept DOI for the software in general, or the version DOI when exact reproducibility
requires the precise archived release.

## Provenance for derived datasets

When a study deposits a collected dataset, record its provenance alongside the deposit so reviewers
can verify that the data were frozen as described:

```python
import gbfs_toolkit as gb

gb.generate_manifest("lake/")          # SHA-256 per Parquet partition plus a system/date summary
gb.coverage_report(panel, expected_freq="5min")   # per-station uptime and longest gap, no imputation
```

The toolkit never imputes missing data. Gaps stay `NaN` and are quantified rather than smoothed, so
the reported coverage reflects what was actually observed.

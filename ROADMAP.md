# Roadmap

Where `gbfs-toolkit` is going, in the order it is likely to get there. It is a statement of intent, not
a promise of dates: items move when they are ready, and the [changelog](https://github.com/cycling-data-lab/gbfs-toolkit/blob/main/CHANGELOG.md) says what actually
shipped. Versions follow [SemVer](https://semver.org) and the [API policy](docs/api-policy.md).

## What the library is for, and what it is not

`gbfs-toolkit` collects, checks and documents GBFS bike-share data, and stays **generic**: it works on
any system that publishes a GBFS feed, hard-codes no operator, country or path, and ships no data of its
own beyond a small synthetic example. It is a library, not a service: it runs nothing in the background,
schedules nothing, hosts nothing, uploads nothing and redistributes no data. A method enters the library
when it is documented, tested and ready to be used by others.

## Now: 2.1 (data-lake modules, experimental)

Nine modules to take data from a feed to a dataset someone else can trust. Each is public and tested,
and **experimental**: names, parameters and output columns may change in a minor release while they are
used on more systems. They are documented under *Data lake* in the manual.

| Module | What it adds |
|---|---|
| `collect` | a polite collector: required User-Agent, feed `ttl` and back-off respected, missing values kept missing and typed, fragments gathered into one Parquet file per system and day |
| `quality` | daily coverage per system (`ok`, `partial`, `outage_collector`, `outage_operator`), collection gaps, silent feeds, an incident registry, and three ambiguity indicators that flag and never delete |
| `aggregate` | availability by 15 minutes, hour and day with fixed definitions, and the property that the sum of `n_obs` is the number of input rows at every level |
| `store` | a Hive-partitioned Parquet lake (system, year, month), common column names, UTC and local time, optional DuckDB views |
| `history` | a dated version of a metadata feed, kept only when its content changes |
| `stations.match` | continuity of station identifiers from one period to the next |
| `trips` | readers for published trip files (Lyft/Motivate, Urban Sharing, Bicycle Transit Systems, Vélomagg) into one schema, with explicit time zones |
| `release` | a frozen folder for a closed period: data, coverage, incidents, Frictionless data package, Croissant metadata, README, checksums |
| `repro` | a content fingerprint and a data manifest, verification, samples for continuous integration |
| CLI | `gbfs collect`, `gbfs compact`, `gbfs quality`, `gbfs release`, `gbfs verify` |

## Done in 2.1: volume, correctness, documentation

- **Large volumes.** `aggregate`, `quality` and `store` read an Arrow table, a DuckDB relation or a lake
  path as well as a frame, computed by DuckDB when the extra is installed and window by window in pandas
  otherwise, with identical results; the collector writes fragments and `compact_collected` gathers each
  closed day atomically. A benchmark on 42 million rows is in `benchmarks/`.
- **Open points of 2.0.1.** Seven behaviours now have an opt-in correction and a `FutureWarning` that
  announces the default of 3.0 (the changelog's *Deprecated* section lists them). Two stay open on purpose:
  the A4 projection of `audit_static` and the nights counted by `detect_frozen_stations`.
- **Typed results.** `audit_static` returns an `AuditReport` (a DataFrame subclass), `QualityReport` reads
  like its two frames, and the lake modules declare columns and logical dtypes that tests check.
- **Property-based tests** of aggregates, coverage, fingerprints, station matching, the lake round trip
  and a frozen release.
- **Trips.** A reader for the Vélomagg file (Montpellier, ODbL), without the account column.
- **Documentation.** A tutorial, four recipes, versioned docs configured with `mike`, and a Croissant file
  validated with the MLCommons `mlcroissant` package.

## Next: 2.2

- **Decide the defaults of 3.0.** Collect feedback on the seven announced changes; the major release
  switches them together, with the A4 projection and the frozen-night rule decided separately.
- **Promote modules to stable** as they meet the criteria below (the engines, the lake layout and the
  fragment layout are the candidates).
- **More trip formats**, each with a sample file and a verified description.
- **Station history by intervals**, a generic version of the validity intervals of a station's id.

## Later

- **Promotion to stable.** An experimental module becomes stable when it has been used on several
  systems without a breaking change for two minor releases, its documentation is complete, and its
  output columns are covered by the contract tests. Promotion is announced in the changelog; nothing
  stable is demoted.
- **More trip formats.** Readers are added for formats that come with a verified description and a
  sample file; none is guessed. Contributions are welcome through an issue with a sample.
- **GBFS evolution.** Follow the specification's new versions and fields as operators adopt them.

## How to take part

Open an issue with a feed that breaks an assumption, a trip file we do not read, or a definition you
disagree with: a small sample (or the URL of a public feed) is the most useful thing you can attach.
See [CONTRIBUTING](https://github.com/cycling-data-lab/gbfs-toolkit/blob/main/CONTRIBUTING.md). Security reports go through [SECURITY](https://github.com/cycling-data-lab/gbfs-toolkit/blob/main/SECURITY.md).

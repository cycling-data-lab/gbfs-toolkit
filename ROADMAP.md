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
| `collect` | a polite collector: required User-Agent, feed `ttl` and back-off respected, missing values kept missing and typed, one Parquet file per system and day |
| `quality` | daily coverage per system (`ok`, `partial`, `outage_collector`, `outage_operator`), collection gaps, silent feeds, an incident registry, and three ambiguity indicators that flag and never delete |
| `aggregate` | availability by 15 minutes, hour and day with fixed definitions, and the property that the sum of `n_obs` is the number of input rows at every level |
| `store` | a Hive-partitioned Parquet lake (system, year, month), common column names, UTC and local time, optional DuckDB views |
| `history` | a dated version of a metadata feed, kept only when its content changes |
| `stations.match` | continuity of station identifiers from one period to the next |
| `trips` | readers for published trip files (Lyft/Motivate, Urban Sharing, Bicycle Transit Systems) into one schema, with explicit time zones |
| `release` | a frozen folder for a closed period: data, coverage, incidents, Frictionless data package, Croissant metadata, README, checksums |
| `repro` | a content fingerprint and a data manifest, verification, samples for continuous integration |
| CLI | `gbfs collect`, `gbfs quality`, `gbfs release`, `gbfs verify` |

## Next: 2.2 (volume, correctness, documentation)

- **Large volumes.** DuckDB and Arrow backends so that `aggregate`, `quality` and `store` work on lakes
  larger than memory, a compaction step from collected day files into the lake, and benchmarks that show
  where the pandas path stops being enough. DuckDB and `pyarrow` remain optional extras; the default
  install stays small.
- **Open points of 2.0.1.** Seven behaviours were documented rather than changed, because changing them
  would move published numbers. They are listed under *Open points* in the changelog and will be decided
  one by one, each with an opt-in switch first and a change of default only in a major version:
  how a missing count enters the rates of `availability_stats`, `service_reliability_index` and
  `boundary_stress`; a station with no count at all in `station_state`; nested zones in
  `coverage_stats`; local-time bins in `resample_panel`; the row order of `join_exogenous_timeseries`;
  and two documented behaviours of the experimental flow simulator.
- **Typed results.** Results that are tables of known columns (coverage, incidents, matches, trips,
  aggregates) get explicit schemas and, where useful, typed containers, so a downstream project can rely on
  columns and dtypes with a static checker.
- **More property-based tests** of the invariants that matter to a user: conservation of observations,
  independence from row order and from the chunking of a read, round trips of the lake and of the
  incident registry, idempotence of a release.
- **Documentation.** A tutorial from a first feed to a frozen release, a how-to on running a collection
  for months (disk, restarts, what to monitor), and a page on reading Croissant and Frictionless files.

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

# Changelog

All notable changes are documented here ([Keep a Changelog](https://keepachangelog.com),
[SemVer](https://semver.org)).

## [2.0.0](https://github.com/cycling-data-lab/gbfs-toolkit/compare/gbfs-toolkit-v1.7.2...gbfs-toolkit-v2.0.0) (2026-06-28)


### ⚠ BREAKING CHANGES

* pre-1.0 consolidation — pure analysis fns, v3 schemas, cut liabilities

### Added

* 1.1.0 — v3 conformance, language-nested feeds, strict frozen mode ([b76e763](https://github.com/cycling-data-lab/gbfs-toolkit/commit/b76e7639b7ab5d4b2ca02ea13d70299c9dc98a20))
* advanced descriptive analytics (1.4.0) ([200a7fa](https://github.com/cycling-data-lab/gbfs-toolkit/commit/200a7fab5e3c4aa44d70e094c83097b57bc3750c))
* audit_catalogue (batch fetch+audit) + inter-rater agreement helpers ([ca0c7dd](https://github.com/cycling-data-lab/gbfs-toolkit/commit/ca0c7dd7c33ca829fc19a8150d9e2bff8c764bdd))
* **audit:** a7_scope and a4_sigma options on audit_static (1.2.0) ([2427a56](https://github.com/cycling-data-lab/gbfs-toolkit/commit/2427a5620388392fb8501467b4a71cc5ea620ade))
* **audit:** capacity_convention (the six capacity semantics) ([d2e98dd](https://github.com/cycling-data-lab/gbfs-toolkit/commit/d2e98dd7e7ba4c0db0b8a0c30dfbb0361f308616))
* **audit:** classify_from_vehicle_types (feed-intrinsic A1) ([e4e3389](https://github.com/cycling-data-lab/gbfs-toolkit/commit/e4e33892fca2dcaf0aea4ca8510a7891993d4129))
* **audit:** classify_from_virtual_station + flag_sentinel_coordinates ([5496432](https://github.com/cycling-data-lab/gbfs-toolkit/commit/5496432e8641aba25db43eca50bf5629525f1431))
* **audit:** overcapacity_ratio + reclassify_overcapacity (A3 mechanism) ([e32307b](https://github.com/cycling-data-lab/gbfs-toolkit/commit/e32307ba62b343169b0652447a0d31abf4d86302))
* **audit:** parameterize thresholds + audit_sensitivity + flag_rate_ci ([4bff531](https://github.com/cycling-data-lab/gbfs-toolkit/commit/4bff531a0027895c5799052e5ee2e1d3b224815c))
* **cli:** context-aware output (rich table, --json) behind [cli] extra ([6ad8143](https://github.com/cycling-data-lab/gbfs-toolkit/commit/6ad81435c191ada3f531e88bf2b4315a04e4125f))
* **cluster:** modern methods + named station typologies ([ff4bbfe](https://github.com/cycling-data-lab/gbfs-toolkit/commit/ff4bbfe51bd948c66fc136ed3c0f19002f25d102))
* daily-use functions + pre-1.0 schema hardening (from Gemini review) ([b81ff87](https://github.com/cycling-data-lab/gbfs-toolkit/commit/b81ff871acd778592e2b1d965f20145e8f4d4acb))
* descriptive research-indicator layer (1.3.0) ([4304df8](https://github.com/cycling-data-lab/gbfs-toolkit/commit/4304df8bc588fcc6909b20f9afbe113b1927950c))
* ergonomic one-liners — drop_flagged, occupancy, filter_vehicles/ebikes, catalogue memo ([2225cbc](https://github.com/cycling-data-lab/gbfs-toolkit/commit/2225cbcd84838b40522be09e2c64e5ff6f107f9b))
* feed governance, service stress and panel ergonomics (v1.6.0) ([b9ae04f](https://github.com/cycling-data-lab/gbfs-toolkit/commit/b9ae04f57000e0cd886b4d7b684d6362c7695ddd))
* fetch/scrape layer — GBFSFeed + one-liners (availability, audit_feed) ([2190735](https://github.com/cycling-data-lab/gbfs-toolkit/commit/219073586533c875e0b9be2839f0c272a0a987c0))
* **fetch:** fetch_multiple(progress=True) feedback + doctests ([683adb2](https://github.com/cycling-data-lab/gbfs-toolkit/commit/683adb2e41c0f5af2b532fa0a69e1741ccc38400))
* **fleet:** detect_ghost_vehicles — flag immobile units from a vehicle panel ([3de369d](https://github.com/cycling-data-lab/gbfs-toolkit/commit/3de369d64fdfa6d432e282e0ae341954be92e415))
* **fleet:** reconcile docked + free-floating feeds into one authoritative tally ([09c6b68](https://github.com/cycling-data-lab/gbfs-toolkit/commit/09c6b68d1e0b76c149d672d2573a79f9c22f2896))
* **geofencing:** service-area zones, point-in-zone joins, equal-area density ([add8349](https://github.com/cycling-data-lab/gbfs-toolkit/commit/add8349659e2a158a4638d958ef4168bee61f9ca))
* **geo:** GeoKDTree — shared great-circle spatial-join primitive (pre-freeze) ([e3ba0d0](https://github.com/cycling-data-lab/gbfs-toolkit/commit/e3ba0d05298ad717be31c783c36b5d36d327d65a))
* helpers distilled from the lab's research code ([648d4d4](https://github.com/cycling-data-lab/gbfs-toolkit/commit/648d4d432db95d36b6e2c43041a4f7fdaafda494))
* library-API conventions — .gbfs accessor, load_example, show_versions, schema validate/coerce, feed repr ([ee04079](https://github.com/cycling-data-lab/gbfs-toolkit/commit/ee0407953707107642bfb57fbeb2f999c305e923))
* mass-conserving flow simulator and empirical compiler ([#6](https://github.com/cycling-data-lab/gbfs-toolkit/issues/6)) ([66567f9](https://github.com/cycling-data-lab/gbfs-toolkit/commit/66567f92bc1cfb604794c4126c6a8c4ff03c370c))
* **osm:** station surroundings within a radius (features_within, station_surroundings, enrich_with_osm) ([46aaacb](https://github.com/cycling-data-lab/gbfs-toolkit/commit/46aaacba9a17d4eaa9da921bf9192db3d50a6fc9))
* research algorithms (FDR, equity, rebalancing tension, resampling) ([d428f5a](https://github.com/cycling-data-lab/gbfs-toolkit/commit/d428f5a578b2e38ad6cef5bb91f0754c3769c6cd))
* research helpers — stockout episodes, turnover, network changes, accessibility, geojson, joins ([513aa14](https://github.com/cycling-data-lab/gbfs-toolkit/commit/513aa14ca7fe50e440243c99b7c09d611ad5cf70))
* round-2 hardening — schema fields, unified audit, ttl staleness, timezone ([ced6cb5](https://github.com/cycling-data-lab/gbfs-toolkit/commit/ced6cb545752ebb47d7063cadf4a0e9360c6d43f))
* **stats:** coverage_stats — density, nearest-neighbour, Clark-Evans dispersion ([846417c](https://github.com/cycling-data-lab/gbfs-toolkit/commit/846417cfa80dfd68109e5d4eddd5af1613c5332a))
* **stats:** descriptive summaries — system_profile, compare_systems, concentration, availability_stats ([4e77bae](https://github.com/cycling-data-lab/gbfs-toolkit/commit/4e77baed3a601b849c21b3b555dfa5acba7e439b))
* **stats:** standard spatial/inequality algorithms — Moran's I, Ripley's K/L, Lorenz, Theil ([4aacb1d](https://github.com/cycling-data-lab/gbfs-toolkit/commit/4aacb1d606d292f8c8c84908b5e90c8a42b4de70))
* synthetic city generator and graph-signal primitives ([#5](https://github.com/cycling-data-lab/gbfs-toolkit/issues/5)) ([36e35be](https://github.com/cycling-data-lab/gbfs-toolkit/commit/36e35be94661ee709f28187f8211fcb782f9f72b))
* **timeseries:** column projection + predicate pushdown in build_availability_panel ([0974173](https://github.com/cycling-data-lab/gbfs-toolkit/commit/09741735419f4427d43fe00b8f8f6ca5011b7e99))
* v0.3 longitudinal data lake (parquet panel + net-flow) ([44a5645](https://github.com/cycling-data-lab/gbfs-toolkit/commit/44a564590e111b54f91eed8d42f87af0da713a9f))
* v0.4 station clustering (spatial / spectral / diurnal profiles) ([a931caf](https://github.com/cycling-data-lab/gbfs-toolkit/commit/a931cafd810493368208b7cb6bc3bdb70c0e8a0d))
* v0.5 multimodal — bikeshare ↔ transit feeders (BYOG GTFS) ([c74686a](https://github.com/cycling-data-lab/gbfs-toolkit/commit/c74686aa4756dacc4acb0a352751ca2333d30d5a))
* v1.0-readiness — provenance, polite networking, errors, regions/alerts ([23eb3e4](https://github.com/cycling-data-lab/gbfs-toolkit/commit/23eb3e4823e94cbc2753f640d11e618c43474395))


### Fixed

* accept GBFS 3.0 num_vehicles_available in to_canonical_station_status (1.0.1) ([d226dab](https://github.com/cycling-data-lab/gbfs-toolkit/commit/d226dab1dc9d948f9583b458045bbfd03b4d2805))
* **ci:** pin mypy to python 3.12 target and the 3.12 job ([4ddfb25](https://github.com/cycling-data-lab/gbfs-toolkit/commit/4ddfb2505852896e24fa762b4e2294acab858388))
* generate LaTeX in format_paper_summary without jinja2 (v1.6.1) ([8b458d7](https://github.com/cycling-data-lab/gbfs-toolkit/commit/8b458d745c59fb351cf4c3228607d8ca0e90ae8f))
* hardening pass — nullable dtypes, dockless-aware A7, antimeridian A5, mass-conservation net flow ([a6709c5](https://github.com/cycling-data-lab/gbfs-toolkit/commit/a6709c5cd27f565c131ef9148e47979c91f32fac))
* pandas 3.0 compatibility for daily frequencies; add benchmark suite (v1.7.2) ([826280f](https://github.com/cycling-data-lab/gbfs-toolkit/commit/826280fb8276516f9ec84bb0af172c6ff4f9ee78))


### Changed

* centralise shared helpers in _internal (DRY) ([952b14a](https://github.com/cycling-data-lab/gbfs-toolkit/commit/952b14a46dfabd4e5008ecb4a677137f9d749962))
* extract the research-indicator layer into gbfs_toolkit.metrics ([5b52547](https://github.com/cycling-data-lab/gbfs-toolkit/commit/5b52547a14d4be97012f915f09ecbd22ddc2a076))
* layered package architecture (core/io/audit/spatial/analytics/interfaces) ([16b6376](https://github.com/cycling-data-lab/gbfs-toolkit/commit/16b6376fd269e43c63f19706389c29a653761af3))
* pre-1.0 consolidation — pure analysis fns, v3 schemas, cut liabilities ([18790dc](https://github.com/cycling-data-lab/gbfs-toolkit/commit/18790dca8bd5a59c8cb21e16e5e0af1f662faa55))
* split analytics/spatial into domain modules (engineering pass, phase 4) ([e634e5e](https://github.com/cycling-data-lab/gbfs-toolkit/commit/e634e5efcc8dd6d515fa5c57ee2c6554f372a31f))


### Documentation

* add scenarios 08-10 (reliability, context, macro) + manifest note ([87d892d](https://github.com/cycling-data-lab/gbfs-toolkit/commit/87d892d79af402b8b5cb90ec8c4119738cb5a2d5))
* add the signature scenario — free-floating & ghost fleets ([bc3f76a](https://github.com/cycling-data-lab/gbfs-toolkit/commit/bc3f76aad7e86c175021f4b7df17653f675244b0))
* add Zenodo DOI (concept 10.5281/zenodo.20992153) to citation metadata ([3be6a23](https://github.com/cycling-data-lab/gbfs-toolkit/commit/3be6a23d8ded46062b62fecc8e691613d9b4f9f4))
* API reference nav, full Examples coverage, library-wide See Also links ([2a7b505](https://github.com/cycling-data-lab/gbfs-toolkit/commit/2a7b5058e6f963801534780821dea01e21b92a6e))
* dedicated how-to page per example with walkthroughs ([fd10cc5](https://github.com/cycling-data-lab/gbfs-toolkit/commit/fd10cc5f1ad4ee4b9c5bf61365a5ab4133e3790a))
* Diataxis structure, curated landing, citing/data-model/glossary pages ([68ad616](https://github.com/cycling-data-lab/gbfs-toolkit/commit/68ad616f975d7569d8a306c6d9e43d3834a4ad30))
* doctested Examples on the analytical API + doctest governance ([ce7bc1f](https://github.com/cycling-data-lab/gbfs-toolkit/commit/ce7bc1f17b720afb53ede070cebd596af950a4dc))
* document the great-circle weighting choice in the methodology ([e509975](https://github.com/cycling-data-lab/gbfs-toolkit/commit/e5099750337be142b109c862021f56e960f7e77c))
* drop README references to removed fetch_osm_around and rebalancing flag ([ee397b2](https://github.com/cycling-data-lab/gbfs-toolkit/commit/ee397b2217eb13ed1698a6be363036af1728f812))
* empirical validation section in methodology ([0cc862b](https://github.com/cycling-data-lab/gbfs-toolkit/commit/0cc862bb629a2ae7d57cc9d8c9a0f23ba65833d7))
* **examples:** add four runnable end-to-end example scripts ([b1c5fb8](https://github.com/cycling-data-lab/gbfs-toolkit/commit/b1c5fb80d2c30b4d5e05384f377cee87ed1a3aba))
* explode the API monolith into a generated per-function catalogue ([9cc3a6f](https://github.com/cycling-data-lab/gbfs-toolkit/commit/9cc3a6fca55485dd3bfc8bdc661e4abb81782a53))
* human-validation explanation page + fuse rigour/comparative scenarios ([1c477b5](https://github.com/cycling-data-lab/gbfs-toolkit/commit/1c477b59f3287d21cbe817859fe1703fae012cbe))
* MkDocs Material site with auto API reference (mkdocstrings) ([b3a5eb1](https://github.com/cycling-data-lab/gbfs-toolkit/commit/b3a5eb1a31ce29001716053e10e11edb6272deac))
* **nav:** standard Diataxis tabs + imperative how-to labels ([c3f9b59](https://github.com/cycling-data-lab/gbfs-toolkit/commit/c3f9b5959dcd10a9e358c49dfa460a670c3821db))
* professional function-reference standard + full-surface scenarios ([43b382c](https://github.com/cycling-data-lab/gbfs-toolkit/commit/43b382c8dbfab352e2905daf49c6bc95a91d4b4f))
* record the v1.5.0 Zenodo version DOI (10.5281/zenodo.20998334) ([5126482](https://github.com/cycling-data-lab/gbfs-toolkit/commit/512648240277f04bbacdcea7711d9535c33b39f5))
* research-grade visual design and richer examples ([a994fe9](https://github.com/cycling-data-lab/gbfs-toolkit/commit/a994fe98d8d2bc2e3ea13c4140158b827811ce85))
* research-register rewrite, modern MkDocs site, math methodology ([d5554de](https://github.com/cycling-data-lab/gbfs-toolkit/commit/d5554debf30a3d85e641a2c42e11a3de4bb49ad8))
* scientific-credibility pass (real audit, threshold rationale, refs, reproducibility) ([1d5dcb9](https://github.com/cycling-data-lab/gbfs-toolkit/commit/1d5dcb93acae9ee68bd2581c2ad84e4a3374e922))
* versioned site (mike), DRY How-To migration, more doctested Examples ([e3b88ef](https://github.com/cycling-data-lab/gbfs-toolkit/commit/e3b88eff0fe8ea9618feb7d926b08cf40fb05790))

## [1.7.2] - pandas 3.0 compatibility and benchmarks

### Fixed
- **pandas 3.0 compatibility.** `offset_minutes` (behind `service_reliability_index`,
  `temporal_concentration`, `turnover`, `fleet_turnover_proxy`, ...) raised a spurious
  "not a fixed-width frequency" error for `"1D"` on pandas 3.0, because
  `pd.Timedelta(Day())` now raises there. It uses the cross-version `offset.nanos`
  primitive again, so daily frequencies work on both pandas 2.x and 3.0. This is the bug
  the new core-only CI job (the only one running on the latest pandas) caught.

### Added
- A `benchmarks/` suite (`pytest benchmarks/ --benchmark-only`) profiling the heaviest
  descriptive functions on realistic synthetic panels, run informationally in CI. The
  core-only CI job now also runs the dependency-free test files, so a pandas-major
  incompatibility is caught before release.

## [1.7.1] - supply-chain and hygiene

### Changed
- **Supply chain.** All GitHub Actions are now pinned by full commit SHA (not a moving
  tag), and the CI workflow runs with least-privilege `contents: read`.
- **Dependency policy.** Documented (README): lower bounds only, following SPEC 0;
  speculative upper caps are avoided because they cause resolution conflicts without
  guarding against real breakage. Support tracks SPEC 0 / NEP 29.
- Internal: the GBFS timestamp parser is a single `parse_gbfs_timestamp` helper in
  `core` (the byte-identical `_utc` / `_utc_ts` copies in the io layer were merged).

### Added
- A `feature_request` issue template (the governance set is now complete).
- A pytest `filterwarnings` rule that silences the upstream pandas 2.3 / numpy 2.5
  `pd.Timedelta` generic-unit `DeprecationWarning` (an internal-pandas issue, not our
  usage), so genuine warnings stay visible in the test output.

## [1.7.0] - correctness, consistency and hardening (professionalism audit)

### Deprecated
- `dynamic_gini_index(target_col=...)` and `temporal_autocorrelation(column=...)` are
  renamed to `value_col` for consistency with the rest of the library. The old keywords
  still work for one release cycle and emit a `FutureWarning`.

### Changed
- **Uniform validation contract.** `concentration_metrics`, `lorenz_curve`, `morans_i`,
  `ripley_k`, `coverage_stats` and `station_state` now raise the didactic `SchemaError`
  (via `require_columns`) on a missing required column instead of a raw `KeyError`.
  `system_profile` stays deliberately lenient (a profile/describe works on any frame).
- **Internal consolidation.** The equirectangular projection behind `ripley_k`,
  `coverage_stats` and the clustering helpers now routes through the single
  `project_meters` helper; the A3 ratio threshold lives in `core.models` with the other
  audit thresholds.
- **io error taxonomy.** `fetch_feed_json` now raises `GBFSFetchError` (not a raw
  `requests.HTTPError`) on a 4xx/5xx or a malformed body, and `resolve` raises
  `GBFSDiscoveryError` (a `KeyError` subclass) for an unknown `system_id`, so
  `except GBFSError` catches both as the error hierarchy promises.
- The `gbfs` CLI now prints a one-line message to stderr and exits with code 2 on a
  missing file, malformed JSON or fetch failure, instead of dumping a Python traceback.
- **Release pipeline gates on tests.** `release.yml` now runs the suite (py3.10 + py3.12)
  and only builds/publishes to PyPI if it passes, so a tag whose tests are red can no
  longer ship a wheel.
- **Documentation cross-references render.** ~120 Sphinx `:func:`/`:class:`/`:data:`
  roles (which displayed as raw text under mkdocstrings) were rewritten to the
  mkdocstrings autoref form.
- Internal hygiene: the panel-flatten idiom is now the single `panel_frame` helper (10
  call sites de-duplicated), the time-of-day bucket helper is reused instead of inlined,
  and `require_columns` (the validation primitive) is now public for extension authors.

### Fixed
- **Join-key dtype mismatch (silent wrong results / merge error).** `to_canonical_vehicles`
  and `to_canonical_station_info` left `vehicle_type_id` / `region_id` numeric while their
  lookup tables coerced them to strings, so `join_vehicle_types` and region joins failed
  (all-`NaN` or a merge error) for any feed using integer ids. All foreign keys are now
  `string`-typed on both sides.
- **`spatial_outage_redundancy`** gave wrong results on real sparse panels: an
  *unobserved* neighbour was counted as empty (so neighbourhood deserts were
  over-reported), and duplicate `(station, timestamp)` polls were summed rather than
  de-duplicated. A systemic outage now requires at least one *observed* neighbour and
  treats unobserved neighbours as unknown; repeated polls are de-duplicated (last kept).
- **`boundary_stress`** nulled the whole drop-off metric when a `capacity` column was
  present but all-`NaN` (a common GBFS case). Only a *finite* non-positive capacity now
  means "no physical docks"; missing capacity is treated as unknown.
- **Non-fixed frequencies** (`service_reliability_index`, `temporal_concentration`) now
  raise a clear `ValueError` for offsets with no constant width (`"ME"`, `"W"`, ...)
  instead of a cryptic internal error.
- `spatial_outage_redundancy` is now **order-independent**: a duplicate
  `(station, timestamp)` is resolved deterministically (highest reported count) rather
  than by input row order.
- `_hull_area_km2` (behind `ripley_k` / `coverage_stats`) uses `nanmean`, so a single
  `NaN` coordinate no longer poisons the projected area.
- `vehicle_id_persistence` coerces timestamps with `errors="coerce"` (a bad timestamp
  yields `NaT` rather than raising), matching `audit_dynamic`.

### Added
- A CI job that installs the package **core-only** (no extras) and runs a smoke import
  plus the dependency-free test subset, so a code path silently needing an optional or
  transitive package fails CI instead of a user's environment.
- An **input-purity** test asserting that public functions never mutate their input
  frames, and least-privilege `permissions: contents: read` on the CI workflow.

## [1.6.1] - patch

### Fixed
- `format_paper_summary(fmt="latex")` now generates the LaTeX table directly instead of
  delegating to `DataFrame.to_latex`, which on some pandas builds routes through the
  Styler and raises `ImportError` when `jinja2` is not installed. The function is now
  dependency-free for both Markdown and LaTeX output.

## [1.6.0] - feed governance, service stress, panel ergonomics

### Added
Four descriptive metrics (grounded in the bike-share literature and an external review)
and a set of everyday panel utilities. All within the descriptive scope (no
origin-destination, routing, prediction or imputation).

- **Feed governance.** `vehicle_id_persistence` characterises whether a feed rotates or
  keeps its `vehicle_id` (the GBFS 2.1+ privacy guidance), via the rolling Jaccard overlap
  of the live id-set and the observed id lifespan. The inverse of this persistence is the
  ceiling on origin-destination identifiability, so it is the check that tells a study
  whether trip-level work is even admissible (a feed property, not trip inference).
- **Service stress.** `boundary_stress` reports the share of time a station sits *near*
  empty or full (absolute thresholds, default `<= 2`), the perceived-unreliability that the
  strict `station_outage_rates` (`== 0`) undercounts; drop-off stress is `NA` for
  free-floating / zero-capacity stations.
- **Spatial redundancy.** `spatial_outage_redundancy` separates a station's local
  stockouts from *systemic* failures where every station within a walking radius is also
  empty, the rupture a user cannot walk around (uses the existing `GeoKDTree`).
- **System-level coverage.** `coverage_report(level="system")` summarises a feed's temporal
  completeness for a paper's data section: window, median cadence, cadence jitter and
  overall station-hours yield (the per-station report is unchanged, `level="station"`).
- **Panel ergonomics.** `add_local_time` (tz conversion that handles the index),
  `resample_panel` (dtype-safe step-function resampling onto a fixed grid),
  `insert_explicit_gaps` (mark collection outages with `NaN` rows so plots break honestly),
  `extract_snapshot_asof` (the city's state at one instant), `to_wide_matrix` (long to
  station-by-time matrix) and `filter_by_bbox` (the missing rectangular spatial filter).

## [1.5.0] - feed-first audit, research algorithms, generated reference

### Added
Audit goes feed-first and batch, and the descriptive analysis surface gains the
algorithms a quantitative study reports. All within the descriptive scope (no
origin-destination, routing, prediction or imputation).

- **Audit pipeline.** `audit_static` now exposes every policy threshold
  (`a5_area_km2`, `a6_tau`, `a7_tau`, `n_min`; `a4_sigma` already public), defaults
  unchanged. `audit_sensitivity` (threshold-robustness sweep with the Jaccard
  overlap of the flagged set) and `flag_rate_ci` (seeded cluster-bootstrap intervals
  on flag rates) make robustness and uncertainty reproducible from one call.
- **Feed-intrinsic classification.** `classify_from_vehicle_types` (A1 car-sharing
  from the GBFS v3 `form_factor`), `classify_from_virtual_station` (free-floating
  from `is_virtual_station`), `overcapacity_ratio` + `reclassify_overcapacity` (the
  A3 conditional-averaging signature), `capacity_convention` (the six capacity
  semantics) and `flag_sentinel_coordinates` (the (0,0) null-island filter).
- **Batch audit.** `audit_catalogue` fetches and audits many systems in one call,
  returning the per-station verdict and a per-system status.
- **Research algorithms.** `fdr_adjust` and `local_morans_i(fdr=True)`
  (Benjamini-Hochberg control for LISA), `theil_index` (between/within decomposable)
  and `palma_ratio` (equity), `two_step_fca` exponential (gravity) decay (E2SFCA),
  `rebalancing_tension` (minimum-work spatial fragmentation via the Wasserstein
  earth-mover distance), `block_bootstrap_ci` + `effective_sample_size` (honest
  uncertainty for autocorrelated series), and `censored_time_ratio` (observability
  loss at saturation).
- **Human-validation helpers.** `krippendorff_alpha`, `cohen_kappa`,
  `wilson_interval` for construct-validity studies.

### Fixed
- `resolve` preferred the operator website `url` over the GBFS auto-discovery
  endpoint (fetched the homepage instead of `gbfs.json`).
- `gini` could return a tiny negative on all-equal inputs (float roundoff).

### Documentation
- The API reference is now a generated per-function catalogue (one page per object
  from `__all__`, a thematic landing) with clickable pandas/numpy/scipy types and a
  source button; versioned with `mike`. Doctested `Examples` on the analytical
  surface (run in CI), a docstring-coverage gate (`interrogate`), and a ten-page
  How-To scenario set (audit, collection, history, equity, rigour, free-floating &
  ghost fleets, reliability, context, macro-scale).

## [1.4.0] - advanced descriptive analytics

### Added
Five research-grade descriptive functions, all on the `.gbfs` accessor and within the descriptive
scope (no origin-destination, routing, prediction or imputation). Closes #2.

- `local_morans_i` (LISA): per-station spatial-autocorrelation hotspots and cold spots with
  conditional-permutation pseudo p-values and HH/LL/HL/LH cluster labels, where the global
  `morans_i` only gives one number. `[geo]`/scipy. Anselin (1995).
- `availability_synchrony`: pairwise correlation of station availability series over their common
  support, returned as an upper-triangle edge list for downstream network analysis (bring your own
  graph). Correlates observed availability only, never trips. O'Brien et al. (2014).
- `diurnal_bimodality`: Sarle's bimodality coefficient of each station's diurnal profile, a
  continuous scalar separating commuter (bimodal) from recreational (unimodal) stations.
- `outage_survival`: empirical survival function and median / P90 time-to-recovery of stockout
  episodes, with the right-censoring caveat stated and never imputed. Kaplan-Meier (1958).
- `temporal_concentration`: per-station Gini of activity across time-of-day bins (temporal peaking),
  the temporal analogue of `dynamic_gini_index`.

## [1.3.0] - descriptive research indicators

### Added
Seventeen pure, descriptive indicators that turn the panel into publication-ready summary
statistics. All are strictly descriptive (no origin-destination, routing, prediction or
imputation), operate on the canonical frames, and are exposed on the `.gbfs` accessor.

- **Service and equity**: `service_reliability_index` (level-of-service probability per station
  and time-of-day), `station_outage_rates` (stockout and saturation fractions),
  `capacity_utilization` (bikes over capacity, nullable), `dynamic_gini_index` (Gini of available
  bikes over time), `two_step_fca` (two-step floating catchment area accessibility, `[geo]`).
- **Observed dynamics**: `flow_asymmetry_ratio` (inflow over outflow), `fleet_turnover_proxy`
  (a lower-bound usage rate per vehicle), `cumulative_imbalance` (drift), `docking_pressure`
  (typical inflow over free docks), `spatial_center_of_mass` (fleet centre of gravity over time),
  `spatial_entropy` (Shannon entropy of the free-floating distribution).
- **Temporal and sampling**: `temporal_autocorrelation` (ACF at hour/day/week lags),
  `aliasing_vulnerability` (a Nyquist-limit diagnostic), `diurnal_summary_stats` (hour-of-day
  mean/median/P5/P95), `temporal_context_features` (is_weekend, time_block, optional is_holiday).
- **Fleet and exogenous**: `vehicle_idle_time` (zombie-fleet share over time),
  `join_exogenous_timeseries` (safe `merge_asof` of weather/traffic onto the panel, bring your own).

## [1.2.0] - reproduce the audit catalogue from the library

### Added
- `audit_static` gains two keyword options so the published `gbfs-audit-catalogue` verdicts
  can be reproduced exactly from the library:
  - **`a7_scope="docked"` (default) or `"all"`**. The default keeps A7 dockless-aware (the
    toolkit's behaviour since 1.0). `"all"` evaluates the null-capacity rate over every
    station, reproducing the catalogue's original A7, under which a fully free-floating system
    with null capacities is flagged.
  - **`a4_sigma=3.0` (default)**. Exposes the A4 nearest-neighbour outlier multiplier for
    sensitivity analysis, so a threshold sweep no longer needs to monkey-patch a module constant.
- Verified byte-identical against the 46 307-station catalogue: with `a7_scope="all"`, all of
  A1 to A7 match the published flags, and `a4_sigma` reproduces the published 2.0 to 4.0 sweep.
- **CLI rendering adapts to context.** `gbfs audit` prints a coloured table when `rich` is
  installed and the output is an interactive terminal, plain text otherwise. New flags:
  `--json` (machine-readable output for pipelines), `--a7-scope {docked,all}`, and `--no-color`.
  `rich` lives behind the new optional `[cli]` extra; the core install is unchanged.
- **`fetch_multiple(progress=True)`** reports progress on a long multi-system pull: a tqdm bar
  when tqdm is installed (also in `[cli]`), otherwise periodic log lines. Feeds are now consumed
  as they complete, and a per-system failure is logged as well as recorded.
- **Doctests** on `occupancy` and `station_state`, run in CI, so the reference examples cannot
  drift from the code.

## [1.1.0] - conformance & robustness (from real-world migration)

### Added
- `detect_frozen_stations` gains **`strict=True`** (a column counts as frozen only if it never
  changes across the whole observed window, not merely a long run) and **`columns=(...)`**
  (require *all* listed columns frozen, e.g. bikes *and* docks). Motivated by cross-validating
  the `gbfs-dynamic-audit` zombie detector against the toolkit.
- Vehicle schema gains **`current_fuel_percent`** (GBFS 3.0 battery fraction).

### Fixed / Changed
- **Language-nested feeds** (old GBFS 1.x/2.x `data.<lang>.<key>`) are now tolerated by every
  normalizer (`to_canonical_station_info` / `_status` / `_vehicles` / `_vehicle_types` /
  `_pricing_plans` / `_system_regions` / `_alerts`), not just discovery. Surfaced by migrating
  bikeshare-data-explorer, whose collectors kept hand-rolled flattening for this reason.
- `to_canonical_station_status` also reads GBFS 3.0 **`vehicle_docks_available`** as a fallback
  for `num_docks_available` (companion to the 1.0.1 `num_vehicles_available` fix).
- CI now runs the `load_example` **doctest**.

## [1.0.1]

### Fixed
- `to_canonical_station_status` now reads the GBFS 3.0 **`num_vehicles_available`** field as a
  fallback for `num_bikes_available` (3.0 renamed it). Surfaced while migrating a real consumer
  (bikeshare-data-explorer) onto the toolkit.

## [1.0.0] - first stable release

Promotes `1.0.0rc1` unchanged (validated by a clean install from PyPI and the full test suite).
The canonical schema and public API are now stable under SemVer. Development status →
Production/Stable.

## [1.0.0rc1] - first public release candidate

Frozen canonical schema and public API after three peer-review passes. Adds `METHODOLOGY.md`
(audit thresholds, the polling/aliasing limit, spatial-stat caveats), `CONTRIBUTING.md`, and a
PyPI Trusted-Publishing release workflow. The sections below list everything since 0.1.0.

### Added (library-API conventions)
- **`.gbfs` pandas accessor**: fluent chaining over the pure functions: `df.gbfs.audit()`,
  `av.gbfs.occupancy()`, `panel.gbfs.net_flow()`, `info.gbfs.join_status(status)`. Single-frame
  ops map directly; two-frame ops take the second frame as the argument.
- **`load_example()`**: a small, deterministic bundled GBFS snapshot (central Paris) for docs,
  doctests and offline tests; returns canonical `(station_info, station_status)`.
- **`show_versions()`**: environment/dependency diagnostic for bug reports.
- **`validate_schema(df, schema)` / `coerce_schema(df, schema)`**: public schema check/cast over
  the canonical contracts (`SCHEMAS` registry); assert or repair a mutated frame before writing it.
- **`GBFSFeed.__repr__` / `_repr_html_`**: readable repr in shells/Jupyter (cached state only,
  never triggers a network call).

### Added (distilled from the lab's research code)
- **`detect_frozen_stations(panel)`**: flags a value stuck unchanged over an active window
  while the feed stays fresh (dead sensor), distinct from staleness (D3) and stockouts. Seen
  reimplemented across three dynamic-audit repos.
- **`flow_balance(panel)`**: per-station inflow/outflow split + source↔sink balance ratio
  (the "Keq" several notebooks computed by hand).
- **`turnover(..., normalize="capacity")`**: capacity-normalised activity, comparable across
  station sizes.
- **`normalize_operator(name)`**: canonical operator brand from a system id/name
  (`smovengo` → `Vélib' Métropole`); non-lossy. Lifted from the audit-catalogue's `detect_operator`.
- **`cyclical_time_features(timestamps)`**: sin/cos calendar encoding (the single most
  duplicated helper across the lab's repos).

### Added (ergonomic one-liners)
- **`drop_flagged(stations)`**: audit and keep the clean subset in one call.
- **`occupancy(availability)`**: the bikes/(bikes+docks) ratio, vectorised, NaN-safe on the
  empty-and-no-docks case (everyone was recomputing it inconsistently).
- **`filter_vehicles(vehicles, types, form_factor=…, propulsion=…)`** and **`ebikes(...)`**:
  resolve vehicle types and filter in one call ("where are the e-bikes?").
- **In-process catalogue cache**: `systems_catalog` now memoises the parsed registry for the
  process (with `refresh=True` to force), so resolving many systems in a loop downloads once.

### Added (research convenience helpers)
- **`stockout_episodes(panel)`**: contiguous empty/full outage *events* per station (start, end,
  duration, n_obs); the service-quality complement to `coverage_report` / `availability_stats`.
- **`turnover(panel, freq="1D")`**: per-station Σ|net_flow| activity proxy (a documented lower
  bound, by the aliasing argument).
- **`network_changes(old, new)`**: diff two station inventories: stations added / removed /
  recapacitated / moved (with distance), for longitudinal studies that span network growth.
- **`stations_near(points, info, radius_m)`**: accessibility primitive: per external POI, count
  of stations within a radius + nearest distance/id (the inverse of `features_within`, for equity).
- **`to_geojson(frame_or_gdf, path=...)`**: export stations/zones to GeoJSON for QGIS / kepler.gl.
- **`join_vehicle_types` / `join_pricing`**: resolve `vehicle_type_id` / `pricing_plan_id` onto a
  vehicles frame so "where are the e-bikes?" / cost joins are one call.

### Quality
- **Input-validation guards**: `join_availability`, `calculate_net_flow`, `coverage_report`,
  `detect_ghost_vehicles` and `link_transit_stops` now raise a clear `SchemaError` naming the
  missing columns instead of a cryptic `KeyError` deep in the call.
- **Test & coverage pass**: 99 → 115 tests, coverage 83% → 94%; added a CI coverage gate
  (`--cov-fail-under=85`). New coverage for the dynamic audit, `fetch_multiple` / module
  one-liners / feed delegators (offline), conditional GET, catalogue cache, the OSM geopandas
  path, panel resampling, manifests, and stats on empty/degenerate inputs.

### Added
- **Ghost-vehicle detection** (`fleet.detect_ghost_vehicles(vehicle_panel, idle_days=14,
  move_threshold_m=50)`): flags free-floating units advertised at the same spot for a long
  span (lost / broken / abandoned but still inflating availability), from a longitudinal
  vehicle panel. Returns per-vehicle `first_seen, last_seen, n_obs, observed_days,
  max_displacement_m, is_ghost`. Completes the dynamic fleet-health story alongside D1–D3.

## [0.8.0] - v1.0-readiness pass (provenance, robustness, methodology)

### Added
- **Provenance / citability** (`timeseries`): `coverage_report(panel, expected_freq)` quantifies
  per-station uptime and longest gap (missingness without imputation); `generate_manifest(lake_dir)`
  emits a SHA-256-per-partition manifest + dataset summary for Zenodo/Dataverse deposits.
- **Polite networking** (`fetch`): `build_session()` (pooled `requests.Session` with
  retry/backoff on 429/5xx, now the default in `fetch_multiple`); `fetch_feed_json(url, etag=...,
  last_modified=...)` does conditional GETs and raises `GBFSNotModified` on HTTP 304; structured
  logging under the `gbfs_toolkit` logger.
- **Exception hierarchy** (`errors`): `GBFSError` base with `GBFSFetchError`, `GBFSDiscoveryError`
  (also a `KeyError` for back-compat), `GBFSValidationError`, `GBFSNotModified`. `SchemaError` now
  subclasses `GBFSValidationError` (and still `ValueError`).
- **New canonical endpoints**: `to_canonical_system_regions` (region lookup) and
  `to_canonical_alerts` (`system_alerts`: disruptions that explain data anomalies), plus
  `GBFSFeed.system_regions()` / `.alerts()`.
- **Catalogue offline fallback**: `systems_catalog` caches successful downloads and falls back to
  the cached copy (with a warning) when the registry is unreachable.
- Documented methodology limits: the **aliasing / polling-Nyquist** caveat on `calculate_net_flow`
  (net flow is a lower bound on activity) and a prominent **edge-effect** warning on `ripley_k`.
- e2e round-trip test (raw → canonical → parquet → panel → net_flow + audit_frames + coverage) and
  CLI tests; coverage 83% → 87%.

### Changed
- Version `0.1.0` → `0.8.0`; development status Alpha → Beta.

## [1.0.0rc1] - pre-1.0 consolidation (second peer-review pass)

<!-- These changes shipped as part of the 1.0.0rc1 release candidate above; they are
     recorded separately here for the detailed pre-1.0 consolidation history. -->

### Changed / Removed
- **Decoupled analysis from fetching.** The join and audit logic are now pure functions on
  canonical frames: `join_availability(info, status)` and `audit_frames(info, status=...,
  ttl_seconds=..., system_id=...)`, so they work on frames read back from a Parquet lake, not
  only on a live `GBFSFeed`. `GBFSFeed.availability()` / `.audit()` are kept as thin
  delegators (no behaviour change for online use).
- The `availability()` `presence` column is now a **fixed-category `Categorical`**
  (`both` / `info_only` / `status_only`) instead of a free string.
- **Removed `osm.fetch_osm_around`**: fetching from OSM's rate-limited Overpass endpoint
  violated the no-HTTP / Bring-Your-Own-GeoDataFrame contract and was a CI/issue liability.
  Fetch with `osmnx` in your own script and pass the result to `enrich_with_osm`.
- **`calculate_net_flow` now reports the observed Δ only.** Removed `account_for_system`,
  `system_net_flow` and `is_rebalancing_suspected`: attributing a flow to rebalancing vs.
  organic demand is not identifiable from availability counts (even with system-wide mass
  conservation), so the library no longer ships a misleading cause label.

### Changed / Fixed (hardening, peer-review pass)
- **Nullable dtypes** in `to_canonical_station_status` (`Int64` counts, `boolean` flags) and
  `to_canonical_vehicles`, so the `availability()` **outer join** inserts `pd.NA` instead of
  silently upcasting integer counts and boolean flags to `float64` (which corrupted equality
  and boolean logic on orphaned stations).
- **A7 (null capacity) is now dockless-aware**: restricted to physical docked stations
  (excludes free-floating *and* virtual anchors, like A2/A6 already did). Mostly-dockless
  systems (Lime/Tier/Bird), whose capacity is null by design, no longer trip A7 spuriously.
- **A5 (bounding box) is antimeridian-safe**: longitudinal extent now uses the smallest
  covering arc, so a system straddling ±180° is no longer reported as Earth-spanning.
- `calculate_net_flow(account_for_system=True)` adds **mass-conservation** context: a
  `system_net_flow` column and a corroborated `is_rebalancing_suspected` that fires only when
  a station spike coincides with a same-sign system-wide change (fleet injection/removal).
  Internal van moves stay indistinguishable from organic demand at panel resolution (documented).
- `fetch_multiple(..., session=...)` accepts a shared `requests.Session` to pool connections
  across systems (avoids TCP/port exhaustion when polling many feeds on a schedule).

### Schema (future-proofing before 1.0)
- `STATION_STATUS_COLUMNS` gains **`is_installed`** (hardware deployed vs. `is_renting`).
- `VEHICLE_STATUS_COLUMNS` gains **`current_range_meters`** (e-bike/battery research) and
  **`pricing_plan_id`** (preserved, not parsed, for equity/pricing joins).

### Added
- **Descriptive stats** (`stats`): `system_profile` (one-glance numeric card of a snapshot:
  stations, capacity, occupancy, % empty/full/disabled/virtual, staleness), `compare_systems`
  (stacks profiles across cities into one table), `concentration_metrics` (capacity Gini +
  top-decile hub share, an equity lens kept *outside* the A1–A7 audit), and
  `availability_stats` (per-station longitudinal scalars: occupancy, time empty/full,
  volatility, diurnal amplitude, peak hour), and `coverage_stats` (station density,
  nearest-neighbour spacing, and the **Clark–Evans** dispersion index: density measured
  against the convex hull, or the real geofencing **service area** when zones are passed).
  Pure, pandas-only, strictly descriptive.
- **Standard spatial / inequality algorithms** (`stats`, numpy/scipy only, deterministic):
  `morans_i` (global Moran's I spatial autocorrelation + analytic z-score/p-value via
  k-NN weights), `ripley_k` (Ripley's K/L multi-scale clustering, density vs. hull or service
  area), `lorenz_curve` (inequality-curve points), and a **Theil index** added to
  `concentration_metrics`.
- **Per-vehicle-type station counts** (`to_canonical_station_vehicle_counts`): melts GBFS
  2.2+/3.x `vehicle_types_available` into a long frame (`STATION_VEHICLE_COUNTS_COLUMNS`), so
  "where are the e-bikes?" is a join: the aggregate `num_bikes_available` can't answer it.
- **Pricing-plan lookup** (`to_canonical_pricing_plans`): parses `system_pricing_plans.json`
  into `PRICING_PLAN_COLUMNS`, resolving the `pricing_plan_id` foreign key for cost/equity work.
- **`target_tz`** on `build_availability_panel`: converts `fetched_at`/`last_reported` to a
  local zone *before* dedup/resample, so daily aggregations cut at local midnight (UTC-midnight
  cuts silently corrupted diurnal analysis).
- **Parquet pushdown** in `build_availability_panel(columns=..., filters=...)`: project only
  the columns you need (join/dedup keys always read) and AND an extra `pyarrow.dataset`
  predicate with the built-in system/date filter, so multi-month / multi-city panels prune
  row-groups *before* materialising instead of OOM-ing.
- **Fleet reconciliation** (`fleet`): `reconcile_fleet_state(station_status, vehicles)` (and
  `GBFSFeed.reconcile_fleet()`) merge the docked aggregate counts and the per-vehicle feed
  into one labelled tally: `available_in_stations`, `free_floating_available/_reserved/
  _disabled`, `total_deployed`, `total_rentable`. Vehicles carrying a `station_id` are
  excluded from the deployed total (so the two feeds don't double-count) and the overlap is
  reported as `docked_in_vehicle_feed` / `double_count_avoided`. `VEHICLE_STATUS_COLUMNS`
  gains **`station_id`** (set when a vehicle is parked at a station, else NA → free-floating).
- **Geofencing / service areas** (`geofencing`, extra `[geo]`):
  `to_canonical_geofencing(raw, system_id=...)` parses `geofencing_zones.json` into a
  canonical `GeoDataFrame` (one row per zone, shapely geometry in EPSG:4326; v2.x
  `ride_allowed` and v3.x `ride_start/ride_end_allowed` reconciled; full per-vehicle-type
  `rules` preserved). `zones_for_points` is the point-in-zone spatial join (which zone each
  station/vehicle sits in), `zone_area_km2` reprojects to an equal-area CRS for metric,
  latitude-comparable density, and `GBFSFeed.geofencing_zones()` fetches them live. Unlocks
  sound spatial-density / equity analysis for free-floating & hybrid systems (the real
  service area, not a station convex hull). New `GEOFENCING_COLUMNS` contract.
- **Station surroundings / OSM** (`osm`, extra `[osm]`): `features_within(points, features,
  radius_m=300, category_col=...)`: the generic "what's nearby" primitive (counts within a
  radius + nearest distance + per-category `n_<cat>` breakdown, on `GeoKDTree`).
  `station_surroundings(info, transit=..., osm=..., radius_m=300)`: one-shot context frame
  combining transit feeders and OSM features. `enrich_with_osm` (reduces any GeoDataFrame
  geometry to representative points; Bring-Your-Own-GeoDataFrame) and the optional
  network-bound `fetch_osm_around` (osmnx). Routing/isochrones stay out of scope.
- **Multimodal** (`multimodal`): `link_transit_stops(info, gtfs_stops_df, radius_m=200)`:
  flags first/last-mile feeder docks near rail/bus by spatial proximity (GeoKDTree;
  Bring-Your-Own GTFS `stops`, no transit API, no schedules). Adds `nearest_stop_id`,
  `nearest_stop_dist_m`, `n_transit_within`, `is_transit_feeder`.
- **Station clustering** (`cluster`, extra `[cluster]`): `cluster_spatial`
  (HDBSCAN/DBSCAN on projected metres), `cluster_spectral` (geographic-affinity spectral
  clustering), and `cluster_diurnal_profiles` (occupancy-profile clustering → typologies).
  Modern options: automatic k by **silhouette** (`n_clusters="auto"`), shape clustering
  (`normalize="zscore"`), **soft GMM** (`method="gmm"`, with `cluster_confidence`),
  shape-aware **DTW** (`method="dtw"`, extra `[dtw]`/tslearn), and weekday/weekend split.
  Plus `diurnal_profiles` (reusable profile matrix) and `label_diurnal_typology`
  (human-readable station types: morning_origin / morning_destination / evening_origin /
  recreational / mostly_empty / mostly_full / stable).
- **Longitudinal data lake** (`timeseries`, extra `[parquet]`): `append_to_parquet`
  (Hive-partitioned by `system_id`/`date`, append-only, concurrent-safe),
  `build_availability_panel` (PyArrow partition-pruned read + dedup on
  `station_id`+`last_reported` + optional resample), `calculate_net_flow`
  (Δ bikes/station + `is_rebalancing_suspected`, NaN across unchanged `last_reported`).
- **`GeoKDTree`** (core `geo`): shared great-circle k-NN / radius index (scipy cKDTree
  over a 3-D unit sphere; EPSG:4326 contract). `find_nearest_stations` now uses it.
- **Fetch / scrape layer**: `GBFSFeed` (discover once, then `.station_information()`,
  `.station_status()`, `.vehicles()`, `.availability()`, `.audit()`, `.snapshot()`,
  `.summary()`); `parse_discovery`; one-liners `availability(url)` / `audit_feed(url)`;
  `fetch_multiple(system_ids)` (threaded, per-system error isolation). `get_json` is
  dependency-injectable for offline use.
- **Dynamic audit** `audit_dynamic` (D1 negative counts, D2 bikes+docks > capacity,
  D3 staleness): the real-time counterpart to the static A1–A7 audit.
- **Derived metrics** `station_state` (empty/full/disabled/normal).
- **Geo helpers** `find_nearest_stations`, `haversine_m`, `to_gdf` (lazy geopandas, `[geo]`).
- **Catalogue** `filter_catalog(country_code=, city=, name=)`: find a system by place.

### Changed (canonical model, pre-1.0 schema hardening)
- StationInfo gains `is_virtual_station`.
- StationStatus gains `is_renting`, `is_returning`.
- VehicleStatus gains `vehicle_type_id` (pedal / e-bike / scooter).
- `last_reported` and `fetched_at` are now tz-aware **UTC** `datetime64[ns, UTC]`
  (previously unix ints) for unambiguous cross-city merges.

## [0.1.0] - 2026-06

Initial scaffold, consolidates GBFS tooling that was scattered across the lab's
research repositories into one tested, installable package.

### Added
- **Canonical data model** (`models`): version-independent `StationInfo`,
  `StationStatus`, `VehicleStatus`, `AuditVerdict` schemas + the A1–A7 rule
  definitions and thresholds.
- **Static semantic audit** (`audit.static.audit_static`): the A1–A7 taxonomy,
  ported from the published `gbfs-audit-catalogue` pipeline, operating on the
  canonical frame (no I/O).
- **Cross-version normalisation** (`normalize.to_canonical_station_info`): GBFS
  2.x string names and 3.x localized-array names; station-type inference.
- **Catalogue discovery** (`catalog.systems_catalog`, `catalog.resolve`): the
  MobilityData global `systems.csv`.
- **CLI**: `gbfs audit <station_information.json>`: the semantic counterpart to
  MobilityData's syntactic `gbfs-validator`.
- PEP 561 `py.typed`, CI (py3.10–3.13 + ruff + build), packaging, 14 unit tests.

### Notes
- Alpha: the public API may change before 1.0. Fetch/archive, the spatial and
  dynamic audits, and analysis panels are planned for 0.2–0.3.

[0.1.0]: https://github.com/cycling-data-lab/gbfs-toolkit/releases/tag/v0.1.0

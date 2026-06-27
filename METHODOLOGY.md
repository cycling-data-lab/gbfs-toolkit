# Methodology, assumptions and limitations

This document states what `gbfs-toolkit` measures, the thresholds it uses, and, just as
importantly, what it *cannot* know. It exists so a reviewer can judge a study built on the
toolkit without reading the source. If you cite the toolkit, cite this page for the audit
definitions and the polling caveats.

## 1. The canonical data model

Ingestion is normalised once into version-independent pandas frames (see
`gbfs_toolkit.models.SCHEMAS`). Two contracts matter for reproducibility:

- **Timestamps are tz-aware UTC** (`datetime64[ns, UTC]`). GBFS 2.x unix seconds and GBFS 3.x
  RFC-3339 strings are both parsed to the same dtype. Convert to local time *explicitly*
  (`build_availability_panel(target_tz=…)`) before any daily or diurnal aggregation. Otherwise
  "days" cut at UTC midnight, i.e. mid-afternoon in the Americas.
- **Nullable extension dtypes** (`Int64`, `boolean`, `string`). A field absent in an older feed
  version is `pd.NA`, never silently `0` or `False`. This survives the outer join in
  `join_availability` (a station present in only one endpoint keeps `pd.NA`, not a float-cast).

## 2. The static semantic audit (A1–A7)

The A1–A7 taxonomy is from Fossé & Pallares (`gbfs-audit-catalogue`). **The thresholds here
are kept identical to the published catalogue so that `audit_static` reproduces the paper's
verdicts.** They are deliberately *not* tuned per-feed; treat them as the published operational
definition, not as free parameters.

| Flag | Definition | Threshold | Level |
|------|-----------|-----------|-------|
| A1 | Out-of-domain inclusion (car-share advertised as bike-share) | `station_type == "carsharing"` | station |
| A2 | Placeholder capacity (one constant non-zero capacity across a docked system) | `nunique == 1`, `median > 0`, `≥ 20` docked stations | system |
| A3 | Structural over-capacity (free-floating anchors) | `station_type == "free_floating"` | station |
| A4 | Geospatial outlier (transposed / isolated coordinate) | nearest-neighbour distance `> max(median + 3·MAD, 1000 m)`, `≥ 5` stations | station |
| A5 | Out-of-perimeter coverage | system bounding box `> 50 000 km²` | system |
| A6 | Zero-capacity docks | `≥ 1 %` of docked stations declare capacity 0, `≥ 20` stations | system |
| A7 | Null capacity field | `≥ 50 %` of docked stations declare capacity NaN, `≥ 20` stations | system |

Design choices worth knowing:

- **A2 / A6 / A7 are docked-aware**: they exclude free-floating *and* virtual stations, whose
  capacity is legitimately constant, zero, or null. Without this, a dockless system (Lime, Tier,
  Bird) would trip every capacity flag spuriously.
- **A4 uses a robust 3σ rule (MAD-rescaled) on nearest-neighbour distance**, with a 1 km floor.
  Formally, station $i$ is flagged when its nearest-neighbour distance $d_i$ satisfies

  $$d_i > \max\!\left(\operatorname{median}(d) + 3\,\mathrm{MAD}(d),\; 1000\text{ m}\right),$$

  evaluated only when at least 5 stations are present. Caveat: dock spacing is closer to a power
  law than Gaussian, so in a system with a dense core and sparse periphery the MAD envelope can
  over-flag genuinely remote suburban docks. The 1 km floor mitigates but does not eliminate this.
  We keep the published rule for reproducibility; if you need a different spatial-outlier model,
  run your own (e.g. DBSCAN noise) on the coordinates and treat A4 as one signal among several.
- **A5 is antimeridian-safe**: the longitudinal extent uses the smallest covering arc, so a
  system straddling ±180° is not reported as Earth-spanning.

### Why these thresholds

The constants are operational definitions inherited from the published catalogue, not free
parameters. Their rationale is worth stating, since unjustified defaults are a common review
objection.

- **MAD rather than standard deviation (A4).** The median absolute deviation has a 50 % breakdown
  point, so the outlier envelope is not itself dragged outward by the very transposed coordinates
  it is meant to catch. A mean-and-standard-deviation rule has a 0 % breakdown point and would mask
  exactly the gross errors of interest. The factor 3 is the conventional three-sigma equivalent
  after the MAD is rescaled to the standard deviation of a Gaussian.
- **The 1 km floor (A4).** In a dense urban core the MAD of nearest-neighbour distance can be a few
  tens of metres, which would flag ordinary spacing as anomalous. The floor sets a physically
  meaningful minimum below which a station is never called an outlier.
- **A 20-station minimum (A2, A6, A7).** System-level rate rules are unreliable on tiny systems, so
  the audit abstains rather than emit a high-variance verdict on fewer than 20 docked stations.
- **The 1 % and 50 % rates (A6, A7).** A6 fires on even a small contamination of zero-capacity
  docks, because a single block of placeholder capacities is enough to bias a capacity-weighted
  metric. A7 requires a majority of null capacities, the signature of a feed that does not populate
  the field at all rather than one with a few gaps.
- **50 000 km² (A5).** This bounding-box area is larger than any single metropolitan bike-share
  service area, so exceeding it indicates merged feeds, out-of-jurisdiction stations, or
  mis-georeferenced coordinates rather than a genuine footprint.

### Empirical validation

The taxonomy is validated empirically in the companion study
([`gbfs-audit-catalogue`](https://github.com/cycling-data-lab/gbfs-audit-catalogue), in
preparation), not only argued from first principles. Four results bear on whether the default
thresholds are defensible.

- **Scale.** The catalogue audits 46 307 stations across more than one hundred French operators, so
  the rules are exercised on real free-floating, docked and hybrid systems rather than a toy sample.
- **Threshold sensitivity (A4).** Sweeping the A4 cutoff from $\sigma = 2$ to $\sigma = 4$ moves the
  flagged share only from 1.29 % to 0.90 % of stations, and the systems most affected are essentially
  unchanged: the Kendall rank correlation of the ten most-flagged cities and operators stays at or
  above 0.956, and the Jaccard overlap of the top ten is 1.0 across the whole range. The published
  default $\sigma = 3$ therefore sits in a flat, stable interior rather than on a knife-edge.

  | $\sigma$ | A4 stations | Flagged share | Top-10 Jaccard |
  |------|------|------|------|
  | 2.0 | 597 | 1.29 % | 1.0 |
  | 2.5 | 543 | 1.17 % | 1.0 |
  | 3.0 | 500 | 1.08 % | 1.0 |
  | 3.5 | 459 | 0.99 % | 1.0 |
  | 4.0 | 415 | 0.90 % | 1.0 |

- **Generalisation.** A leave-one-operator-out cross-validation on seven operators (Bird, Citiz,
  Dott, Pony, Voi, Vélib' Métropole, Vélo&Co) shows each rule firing on a held-out operator where
  its type predicts: the A3 free-floating rule fires on the dockless operators and not on the docked
  ones. This is evidence that the rules encode the intended structure rather than memorising the
  training systems.
- **Robust A4 geometry.** The topology-aware A4 detector removes the large blocks of false positives
  that a naive station-centroid method produces on dockless feeds (on the order of 2 700 spurious
  flags on a single Paris dockless operator alone), which is why A4 operates on nearest-neighbour
  distance rather than distance to a centroid.

A pre-registered, blind author annotation of a stratified sample (n = 422 stations) provides a
construct-validity check of the automated verdicts. Full protocols and per-operator results are in
the companion repository under `experiments/`.

## 3. The dynamic audit (D1–D3) and frozen stations

On a live availability snapshot:

- **D1 negative**: `num_bikes_available < 0` or `num_docks_available < 0`.
- **D2 over-capacity**: `bikes + docks > capacity` (only where capacity is a positive number).
- **D3 stale**: `fetched_at − last_reported` exceeds the feed's advertised `ttl` (plus a 60 s
  clock-skew buffer), or `stale_after_minutes` (default 60) when no `ttl` is given.

`detect_frozen_stations` (longitudinal) is **distinct from D3**: a frozen station has a *fresh*
`last_reported` but a value that never changes over an active window, which is the signature of a
dead sensor rather than a stale fetch. It is also distinct from a legitimate stockout (handled by
`stockout_episodes`). Restrict it to active hours to avoid flagging the normal overnight
flatline.

## 4. Flows are observed, not inferred: the polling Nyquist limit

`calculate_net_flow` reports the **observed Δ** in available bikes between consecutive polls.
`turnover` sums `|Δ|`; `flow_balance` splits it into inflow and outflow. All three share one hard
limit:

> **Aliasing.** Any activity that cancels within a polling interval is invisible. A bike rented
> and returned to the same station between two snapshots yields Δ = 0. These quantities are
> therefore a **lower bound** on true activity. Poll well below the timescale of the dynamics
> you want to measure, and report your polling cadence.

Formally, let $T$ be the true number of vehicle movements at a station over a window and
$\hat{T}$ the turnover observed at polling interval $\Delta t$. Then $\hat{T} \le T$, with equality
only if no station's count ever returns to a previous value within a single interval. Decreasing
$\Delta t$ can only raise $\hat{T}$ toward $T$, never overshoot it, so the estimator is
conservative by construction.

The toolkit deliberately ships **no rebalancing/OD attribution**. Whether a Δ is a rebalancing
van or organic demand is *not identifiable* from station-aggregate counts: even under system-wide
mass conservation, an internal van move (A→B) is indistinguishable from coincident organic trips.
Trip and OD reconstruction belong in dedicated research code, not here.

## 5. Spatial statistics: what is and isn't boundary-robust

- **`coverage_stats`** reports density and the **Clark–Evans** dispersion index (boundary-robust
  enough for an overall verdict). The Clark–Evans aggregation index compares the observed mean
  nearest-neighbour distance to the value expected under complete spatial randomness:

  $$R = \frac{\bar{d}_{\text{obs}}}{\bar{d}_{\text{exp}}},\qquad \bar{d}_{\text{exp}} = \frac{1}{2\sqrt{\rho}},$$

  where $\rho$ is the point density; $R < 1$ indicates clustering, $R \approx 1$ randomness (CSR),
  and $R > 1$ dispersion. Density is measured against the convex hull by default, or the real
  **geofencing service area** when you pass the operator's zones, which is strongly preferred for
  free-floating systems, where a hull badly overstates the footprint.
- **`morans_i`** (spatial autocorrelation) uses row-standardised k-NN weights; significance is the
  analytic z-score under the normality assumption. Global Moran's I is

  $$I = \frac{n}{\sum_{i}\sum_{j} w_{ij}} \cdot \frac{\sum_{i}\sum_{j} w_{ij}(x_i-\bar{x})(x_j-\bar{x})}{\sum_{i}(x_i-\bar{x})^2},$$

  where the $w_{ij}$ are the row-standardised k-NN weights.
- **`ripley_k`** has **no edge correction**. It is biased downward at radii approaching the
  study-area size and is unreliable on irregular real boundaries (coastlines, rivers). Use it for
  *relative* comparison at small radii; prefer Clark–Evans for an overall dispersion verdict.

## 6. Inequality / equity metrics

`concentration_metrics` reports the **Gini** and **Theil** indices of capacity and the
top-decile share; `lorenz_curve` returns the curve points. For station capacities $c_i$ with mean
$\bar{c}$, the Gini index is

$$G = \frac{\sum_{i}\sum_{j} |c_i - c_j|}{2 n^2 \bar{c}},$$

and the Theil index is

$$T = \frac{1}{n}\sum_{i} \frac{c_i}{\bar{c}} \ln\frac{c_i}{\bar{c}}.$$

These are descriptive measures of how capacity is distributed across stations, deliberately kept
*outside* the A1–A7 audit, because concentration is a property of a network's design, not a
feed-quality defect.

## 7. Fleet reconciliation limits

`reconcile_fleet_state` excludes vehicles that carry a `station_id` from the deployed total so the
docked and free-floating feeds do not double-count, and reports the overlap explicitly. It relies
on the operator setting `station_id` correctly; a hybrid feed that lists dock-adjacent free bikes
without it will still double-count. `detect_ghost_vehicles` requires **stable** `vehicle_id`s.
GBFS 2.1+ rotates them for privacy, so on such feeds ghost detection is not meaningful.

## 8. Reproducibility & provenance

For a citable dataset, record `generate_manifest(lake_dir)` (a SHA-256 per Parquet partition plus
a system/date summary) alongside the deposit, and `coverage_report(panel)` to quantify
missingness. The toolkit never imputes: gaps stay `NaN` and are reported, not smoothed.

## 9. References

The audit taxonomy and the statistical estimators rest on the following sources.

- MobilityData. *General Bikeshare Feed Specification (GBFS)*. [github.com/MobilityData/gbfs](https://github.com/MobilityData/gbfs)
- Fossé, R. and Pallares, G. (2026). *A certified, anomaly-flagged reference catalogue for GBFS bike-sharing feeds* (`gbfs-audit-catalogue`). In preparation. The A1–A7 taxonomy and thresholds originate here.
- Clark, P. J. and Evans, F. C. (1954). Distance to nearest neighbor as a measure of spatial relationships in populations. *Ecology*, 35(4), 445–453.
- Moran, P. A. P. (1950). Notes on continuous stochastic phenomena. *Biometrika*, 37(1/2), 17–23.
- Ripley, B. D. (1977). Modelling spatial patterns. *Journal of the Royal Statistical Society: Series B*, 39(2), 172–212.
- Gini, C. (1912). *Variabilità e mutabilità*. Bologna.
- Theil, H. (1967). *Economics and Information Theory*. North-Holland, Amsterdam.

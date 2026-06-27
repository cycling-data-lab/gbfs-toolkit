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

"""Synthetic but faithful GBFS systems, for tests, benchmarks and method development.

A real multi-day station-status archive is heavy and operator-specific. This module
fabricates a deterministic, city-scale system whose behaviour is *faithful* under the
toolkit's own descriptive statistics. Demand is driven by a noisy **land-use mosaic**
(residential, work, transit hub, leisure), not a smooth radial gradient, so the spatial
pattern carries genuine high-frequency content (a dense transit hub dropped in the
periphery is a sharp spatial spike). Each land use has its own diurnal profile;
occupancy is censored at ``[0, capacity]`` (real empty/full episodes); the idiosyncratic
term is an AR(1) (so short-horizon persistence is realistic) plus a spatially correlated
common shock (storms, events hit many stations at once); elevation biases the baseline
(uphill stations drain); capacity is heavy-tailed (a few mega-stations); operators
rebalance at night; weekends are damped and shifted toward leisure. The output is the
same canonical ``(station_information, station_status)`` pair the rest of the toolkit
consumes, so it exercises the real ingestion, audit and time-series path, not a parallel one.

By default occupancy is generated top-down (fast, faithful in distribution: diurnal shape,
spatial structure, persistence, censoring, turnover), which is what tests of descriptive and
spectral methods need. Passing ``od_driven=True`` switches to a mass-conserving gravity flow
of coupled queues, where bikes drain one pole as they fill another: network synchrony then
drops to real-city levels and the dynamics are queue-like, at an O(N^2)-per-step cost. Use it
for origin-destination identifiability and rebalancing studies.

This is fabricated data. Never present it as an observed feed.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from gbfs_toolkit.core.models import coerce_schema, validate_schema

__all__ = ["simulate_city"]

_LAND_USES = ("residential", "work", "transit", "leisure")
_DEFAULT_MIX = (0.45, 0.30, 0.08, 0.17)


def _bump(h: np.ndarray, mu: float, s: float) -> np.ndarray:
    """Gaussian bump in hour-of-day."""
    return np.exp(-((h - mu) ** 2) / (2 * s**2))


def _pairwise_haversine_km(lat, lon):
    """Great-circle distance matrix (km) between all stations."""
    la = np.radians(lat)
    lo = np.radians(lon)
    dla = la[:, None] - la[None, :]
    dlo = lo[:, None] - lo[None, :]
    a = np.sin(dla / 2) ** 2 + np.cos(la)[:, None] * np.cos(la)[None, :] * np.sin(dlo / 2) ** 2
    return 6371.0 * 2 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def _od_occupancy(
    lat,
    lon,
    capacity,
    centrality,
    use_idx,
    activity,
    hod,
    steps,
    rng,
    *,
    trip_rate,
    dist_scale_km,
    rebalancing,
    rebalancing_hour,
    rebalancing_strength,
):
    """Mass-conserving occupancy from a gravity origin-destination flow of coupled queues.

    Bikes leave a station as a Poisson draw and arrive at destinations drawn from a
    distance-decayed, time-varying gravity matrix (morning flow toward job hubs, evening
    toward residential). Because every departure is an arrival elsewhere, when one pole
    empties another fills: network synchrony stays low and the persistence is queue-like
    (a bike sits until taken). Bimodality emerges from the flow, it is not imposed.
    """
    n = len(lat)
    transit = use_idx == _LAND_USES.index("transit")
    D = _pairwise_haversine_km(lat, lon)
    attract = 0.5 + centrality  # central stations pull harder
    P0 = attract[None, :] * np.exp(-((D / dist_scale_km) ** 2))
    np.fill_diagonal(P0, 0.0)
    job = centrality.copy()
    job[transit] += 0.5
    res = 1.0 - centrality
    morning = np.exp(-((hod - 8.0) ** 2) / (2 * 2.5**2))
    evening = np.exp(-((hod - 18.0) ** 2) / (2 * 2.5**2))
    morning /= morning.max()
    evening /= evening.max()

    bikes = 0.5 * capacity
    occ_m = np.empty((steps, n))
    for t in range(steps):
        pull = morning[t] * job + evening[t] * res + 0.1  # where bikes want to go now
        Pt = P0 * pull[None, :]
        Pt /= Pt.sum(axis=1, keepdims=True) + 1e-12
        out_pressure = morning[t] * res + evening[t] * job + 0.05  # who emits now
        lam = trip_rate * activity * out_pressure
        dep = np.minimum(rng.poisson(np.maximum(lam, 0)), bikes)
        bikes = np.clip(bikes - dep + Pt.T @ dep, 0.0, capacity)
        if rebalancing and int(round(hod[t])) == rebalancing_hour:
            bikes = bikes + rebalancing_strength * (0.5 * capacity - bikes)
        occ_m[t] = bikes / np.maximum(capacity, 1e-9)
    return occ_m


def _land_use_profiles(hod: np.ndarray) -> dict[str, np.ndarray]:
    """Diurnal occupancy deviation in roughly [-1, 1] for each land use."""
    resid = np.cos(2 * np.pi * (hod - 3) / 24)  # full at night, drains by day
    work = np.cos(2 * np.pi * (hod - 13) / 24)  # fills through the workday
    transit = _bump(hod, 8, 1.0) - _bump(hod, 18, 1.0)  # sharp two-sided commuter spikes
    transit = transit / (np.abs(transit).max() + 1e-9)
    leisure = _bump(hod, 14, 2.5)
    leisure = leisure / (leisure.max() + 1e-9)
    return {"residential": resid, "work": work, "transit": transit, "leisure": leisure}


def simulate_city(
    *,
    n_stations: int = 300,
    days: int = 14,
    freq: str = "1h",
    center: tuple[float, float] = (48.86, 2.35),
    spread_km: float = 4.0,
    n_clusters: int = 8,
    land_use_mix: tuple[float, float, float, float] = _DEFAULT_MIX,
    capacity_range: tuple[int, int] = (15, 40),
    start: str | pd.Timestamp = "2026-06-01",
    system_id: str = "synthetic",
    base_occupancy: float = 0.5,
    commute_amplitude: float = 0.45,
    activity_tail: float = 0.5,
    elevation: float = 0.12,
    common_shock: float = 0.03,
    spatial_lowfreq: float | None = None,
    spatial_modes: int = 16,
    weekend_factor: float = 0.5,
    phase_jitter: float = 1.5,
    autocorr: float = 0.8,
    noise: float = 0.05,
    rebalancing: bool = True,
    rebalancing_hour: int = 4,
    rebalancing_strength: float = 0.5,
    weather_days: int = 0,
    missing_rate: float = 0.0,
    n_frozen: int = 0,
    od_driven: bool = False,
    od_trip_rate: float = 3.0,
    od_dist_scale_km: float = 1.5,
    seed: int = 42,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fabricate a faithful city-scale GBFS system as canonical frames.

    Returns a ``(station_information, station_status)`` pair. The status frame is a
    *panel*: one row per station and per timestamp on a regular grid, carrying
    ``fetched_at`` so it pivots straight through
    [`to_wide_matrix`][gbfs_toolkit.to_wide_matrix] and
    [`build_availability_panel`][gbfs_toolkit.build_availability_panel]-style analytics.

    Parameters
    ----------
    n_stations, days, freq
        Size of the system and of the time grid (``freq`` is any pandas offset alias).
    center, spread_km, n_clusters
        Geography: cluster centres scatter within ``spread_km`` of ``center`` and stations
        scatter around their cluster, so the network clumps like a real city.
    land_use_mix
        Proportions of (residential, work, transit, leisure). Clusters take a dominant land
        use and stations mostly inherit it (a noisy mosaic), then a few stations are forced to
        transit hubs anywhere, including the periphery, to inject high spatial frequency and
        avoid a smooth, trivially low-frequency demand field.
    capacity_range
        Per-station capacity is drawn in this range, then scaled up for transit hubs (heavy tail).
    base_occupancy, commute_amplitude, activity_tail
        A baseline plus a land-use diurnal swing scaled by per-station heavy-tailed activity.
    elevation, common_shock
        ``elevation`` biases the baseline (uphill stations drain and rarely refill);
        ``common_shock`` adds a spatially correlated shared shock (storms/events), on top of the
        per-station AR(1), so cross-station residuals covary like a real city.
    spatial_lowfreq, spatial_modes
        Experimental knob for spectral studies. When ``spatial_lowfreq`` is given (a number in
        ``[0, 1]``), the land-use demand field is replaced by a single diurnal shape modulated by
        a controlled-spectrum spatial field (see
        [`band_limited_signal`][gbfs_toolkit.band_limited_signal]) whose share of energy in the
        bottom ``spatial_modes`` graph frequencies is ``spatial_lowfreq``. Sweeping it from 0
        (purely high-frequency spatial demand) to 1 (smooth, low-frequency) lets you vary the
        spatial frequency of a city on purpose and watch how spectral methods respond. ``None``
        keeps the realistic land-use mosaic (default).
    weekend_factor, phase_jitter, autocorr, noise
        Weekends scale the commuter swing by ``weekend_factor``; ``phase_jitter`` shifts each
        station's peak by up to that many hours (the school vs the supermarket next door), which
        lowers network synchrony toward the values real cities show; the idiosyncratic term is an
        AR(1) with coefficient ``autocorr`` and innovation scale ``noise``.
    rebalancing, rebalancing_hour, rebalancing_strength
        Nightly operator rebalancing toward 0.5, the signature the dynamic audit looks for.
    weather_days, missing_rate, n_frozen
        Opt-in artefacts: low-demand days, dropped snapshots (polling gaps), frozen stations.
        All default off so the base output is a clean, deterministic full grid.
    od_driven, od_trip_rate, od_dist_scale_km
        When ``od_driven``, occupancy comes from a mass-conserving gravity flow of coupled queues
        instead of the top-down signal: bikes leave as a Poisson draw (rate ``od_trip_rate``) and
        arrive at destinations drawn from a distance-decayed (scale ``od_dist_scale_km``),
        time-varying gravity matrix. Synchrony stays low and persistence is queue-like, at an
        O(N^2)-per-step cost. The default top-down mode is faster.
    seed
        Reproducibility (default 42, the program convention).

    Examples
    --------
    >>> from gbfs_toolkit import simulate_city, to_wide_matrix
    >>> info, status = simulate_city(n_stations=20, days=2, seed=0)
    >>> info.shape[0]
    20
    >>> wide = to_wide_matrix(status)
    >>> wide.shape[1]
    20
    """
    rng = np.random.default_rng(seed)
    lo, hi = capacity_range
    deg_per_km = 1.0 / 111.0
    clat, clon = center
    mix = np.asarray(land_use_mix, float)
    mix = mix / mix.sum()

    # ---- geography: clusters around the centre, stations around clusters
    cl_lat = clat + rng.normal(0, spread_km * deg_per_km, n_clusters)
    cl_lon = clon + rng.normal(0, spread_km * deg_per_km, n_clusters)
    member = rng.integers(0, n_clusters, n_stations)
    jitter = 0.25 * spread_km * deg_per_km
    lat = cl_lat[member] + rng.normal(0, jitter, n_stations)
    lon = cl_lon[member] + rng.normal(0, jitter, n_stations)

    # ---- land-use mosaic: dominant per cluster, noisy per station, transit hubs sprinkled
    cluster_use = rng.choice(len(_LAND_USES), size=n_clusters, p=mix)
    inherit = rng.random(n_stations) < 0.7
    rand_use = rng.choice(len(_LAND_USES), size=n_stations, p=mix)
    use_idx = np.where(inherit, cluster_use[member], rand_use)
    n_extra_hubs = max(1, int(round(0.03 * n_stations)))  # high-frequency spikes anywhere
    use_idx[rng.choice(n_stations, size=n_extra_hubs, replace=False)] = _LAND_USES.index("transit")
    use_name = np.array(_LAND_USES)[use_idx]

    # ---- elevation: smooth field plus noise, biases the baseline downward uphill
    cl_elev = rng.normal(0, 1, n_clusters)
    z = cl_elev[member] + rng.normal(0, 0.4, n_stations)
    z = (z - z.mean()) / (z.std() + 1e-9)

    # ---- capacity: base draw, mega-stations at transit hubs (heavy tail)
    # capacity: operators install standard module sizes, not a uniform integer range, and the
    # size distribution is heavy-tailed (Zipf: many small stations, few hubs). Sample a discrete
    # catalogue a priori; transit hubs draw from the large end.
    _CATALOG = np.array([10, 15, 20, 25, 30, 35, 40, 50, 60, 80])
    bulk = _CATALOG[(lo <= _CATALOG) & (hi >= _CATALOG)]
    if bulk.size < 2:
        bulk = np.array([lo, hi])
    w = 1.0 / np.arange(1, bulk.size + 1) ** 1.2
    capacity = rng.choice(bulk, size=n_stations, p=w / w.sum()).astype(int)
    is_transit = use_idx == _LAND_USES.index("transit")
    big = _CATALOG[hi <= _CATALOG]
    if big.size and is_transit.any():
        capacity[is_transit] = rng.choice(big, size=int(is_transit.sum()))

    activity = np.exp(rng.normal(0, activity_tail, n_stations))
    activity /= activity.mean()
    type_offset = np.array([0.10, -0.10, 0.0, 0.0])  # residential rests fuller
    base_occ = np.clip(
        base_occupancy + type_offset[use_idx] - elevation * z + rng.normal(0, 0.03, n_stations),
        0.15,
        0.85,
    )
    shock_load = rng.normal(1.0, 0.3, n_stations)  # heterogeneous shock exposure
    station_id = np.array([f"S{idx:04d}" for idx in range(n_stations)])

    # ---- time grid and per-land-use diurnal shapes
    steps = int(round(days * 24 * (pd.Timedelta("1h") / pd.Timedelta(freq))))
    grid = pd.date_range(start=start, periods=steps, freq=freq, tz="UTC")
    hod = grid.hour.to_numpy() + grid.minute.to_numpy() / 60.0
    is_we = grid.dayofweek.to_numpy() >= 5
    profiles = _land_use_profiles(hod)
    prof = np.vstack([profiles[name] for name in _LAND_USES])  # (4, steps)
    is_leisure = use_idx == _LAND_USES.index("leisure")
    we_scale_commute = np.where(is_we, weekend_factor, 1.0)
    we_scale_leisure = np.where(is_we, 1.0, 0.3)

    # ---- experimental knob: a spatial field with a controlled low/high frequency mix
    controlled = spatial_lowfreq is not None
    if controlled:
        from gbfs_toolkit.spatial.graph import (
            band_limited_signal,
            knn_adjacency,
            normalized_laplacian,
        )

        Lz = normalized_laplacian(knn_adjacency(lat, lon, k=min(10, n_stations - 1)))
        spatial_weight = band_limited_signal(
            Lz,
            r2_target=float(spatial_lowfreq),
            n_low=min(spatial_modes, n_stations - 2),
            seed=seed,
        )
        diurnal_shape = profiles["transit"]  # one bidirectional shape

    if weather_days > 0:
        all_dates = np.array(sorted(set(grid.date)))
        bad = set(rng.choice(all_dates, size=min(weather_days, len(all_dates)), replace=False))
        weather = np.array([0.5 if d in bad else 1.0 for d in grid.date])
    else:
        weather = np.ones(steps)

    # ---- per-station phase jitter: stations of the same land use peak at slightly different
    # hours (the school vs the supermarket vs the metro 200m apart), so network synchrony drops
    # to the low values real cities show. Land-use mode only; the spectral knob stays clean.
    SIG = None
    if not controlled and phase_jitter > 0:
        delta = rng.uniform(-phase_jitter, phase_jitter, n_stations)
        Pmat = _land_use_profiles((hod[:, None] - delta[None, :]).ravel())
        SIG = np.empty((steps, n_stations))
        for k, name in enumerate(_LAND_USES):
            col = use_idx == k
            if col.any():
                SIG[:, col] = Pmat[name].reshape(steps, n_stations)[:, col]

    # ---- occupancy. Default: top-down land-use signal + AR(1) + common shock (fast). With
    # od_driven: a mass-conserving gravity flow of coupled queues (realistic synchrony, queue
    # persistence, emergent bimodality), at a higher compute cost (O(N^2) per step).
    if od_driven:
        _cd = np.sqrt((lat - lat.mean()) ** 2 + (lon - lon.mean()) ** 2)
        centrality = 1.0 - (_cd - _cd.min()) / (np.ptp(_cd) + 1e-9)
        occ_m = _od_occupancy(
            lat,
            lon,
            capacity.astype(float),
            centrality,
            use_idx,
            activity,
            hod,
            steps,
            rng,
            trip_rate=od_trip_rate,
            dist_scale_km=od_dist_scale_km,
            rebalancing=rebalancing,
            rebalancing_hour=rebalancing_hour,
            rebalancing_strength=rebalancing_strength,
        )
    else:
        occ_m = np.empty((steps, n_stations))
        eps = np.zeros(n_stations)
        shock = 0.0
        innov_sd = noise * np.sqrt(1 - autocorr**2)
        for t in range(steps):
            eps = autocorr * eps + rng.normal(0, innov_sd, n_stations)
            shock = autocorr * shock + rng.normal(0, np.sqrt(1 - autocorr**2))
            if controlled:
                # clean knob: the spatial spectrum is exactly the band-limited field
                det = (
                    base_occ
                    + commute_amplitude
                    * spatial_weight
                    * diurnal_shape[t]
                    * we_scale_commute[t]
                    * weather[t]
                )
            else:
                sig = SIG[t] if SIG is not None else prof[use_idx, t]
                wk = np.where(is_leisure, we_scale_leisure[t], we_scale_commute[t])
                det = base_occ + commute_amplitude * activity * sig * wk * weather[t]
            o = det + eps + common_shock * shock_load * shock
            if rebalancing and int(round(hod[t])) == rebalancing_hour:
                o = o + rebalancing_strength * (0.5 - o)
            occ_m[t] = np.clip(o, 0.0, 1.0)

    bikes = np.clip(np.rint(occ_m * capacity[None, :]).astype(int), 0, capacity[None, :])
    docks = capacity[None, :] - bikes

    # ---- assemble canonical frames (row index t*N + s)
    info = pd.DataFrame(
        {
            "system_id": system_id,
            "station_id": station_id,
            "name": [f"Station {idx} ({use_name[idx]})" for idx in range(n_stations)],
            "lat": lat,
            "lon": lon,
            "capacity": capacity,
            "station_type": "station",
            "is_virtual_station": False,
            "region_id": member.astype(str),
        }
    )
    last_reported = np.asarray(grid.view("int64")) // 1_000_000_000
    status = pd.DataFrame(
        {
            "system_id": system_id,
            "station_id": np.tile(station_id, steps),
            "num_bikes_available": bikes.reshape(-1),
            "num_docks_available": docks.reshape(-1),
            "is_renting": 1,
            "is_returning": 1,
            "is_installed": 1,
            "last_reported": np.repeat(last_reported, n_stations),
            "fetched_at": np.repeat(grid.to_numpy(), n_stations),
            "gbfs_version": "2.3",
        }
    )

    if n_frozen > 0:
        frozen = set(rng.choice(station_id, size=min(n_frozen, n_stations), replace=False))
        first = bikes[0]
        idx0 = {s: i for i, s in enumerate(station_id)}
        mask = status["station_id"].isin(frozen).to_numpy()
        pos = status.loc[mask, "station_id"].map(idx0).to_numpy()
        status.loc[mask, "num_bikes_available"] = first[pos]
        status.loc[mask, "num_docks_available"] = capacity[pos] - first[pos]

    if missing_rate > 0:
        keep = rng.random(len(status)) >= missing_rate
        status = status.loc[keep].reset_index(drop=True)

    info = validate_schema(coerce_schema(info, "station_info"), "station_info")
    status = validate_schema(coerce_schema(status, "station_status"), "station_status")
    return info, status

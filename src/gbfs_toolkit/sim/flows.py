"""simulate_city_flows v2: a research-grade ablation framework on the mass-conserving engine.

Every new behaviour is a vectorised mask or multiplier, never a branch inside the time loop, so
the engine stays O(T * N^2) and strictly mass-conserving. Four axes: heterogeneous multimodality
(heavy vs light hubs), asymmetric topography (uphill penalty baked into the gravity), GBFS data
chaos (ghost bikes + scraper NaNs), and exogenous weather shocks. numpy / pandas only.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# residential, employment, hub_heavy (TGV/RER), hub_light (metro)
_ROLES = ("residential", "employment", "hub_heavy", "hub_light")


@dataclass
class SimConfig:
    n_stations: int = 200
    days: int = 14
    freq: str = "1h"
    internal_minutes: int = 15
    seed: int = 42
    # geography
    center: tuple[float, float] = (48.86, 2.35)
    spread_km: float = 4.0
    n_clusters: int = 8
    # roles / demand
    role_mix: tuple[float, float, float, float] = (0.55, 0.27, 0.10, 0.08)
    trip_rate: float = 12.0
    base_demand: float = 0.6
    mass_tail: float = 1.6  # lognormal sigma of station mass: heavy tail -> few mega-hubs
    beta_km: float = 1.5
    max_trip_km: float | None = 5.0
    speed_kmh: float = 15.0
    # 1. heterogeneous multimodality
    heavy_period_min: float = 45.0
    heavy_spike: float = 10.0
    light_period_min: float = 5.0
    light_spike: float = 1.5
    # 2. asymmetric topography
    topography: bool = True
    climb_penalty: float = 1.2  # gamma: gravity penalty per unit uphill altitude
    # rebalancing (vectorised proportional pull at night)
    rebalancing: bool = True
    rebalancing_hour: int = 4
    rebalancing_strength: float = 0.6
    # 3. GBFS data chaos
    ghost_rate: float = 0.0  # fraction of capacity that is unrentable ghost bikes
    scraper_cell_nan: float = 0.0  # fraction of (station, time) cells set to NaN
    scraper_station_outages: int = 0  # whole-station NaN blocks
    # 4. exogenous weather shocks
    weather_events: int = 0
    weather_drop: float = 0.1  # departure-demand multiplier during a downpour
    weather_len_min: float = 90.0
    # optional injected geometry (the empirical compiler passes a real feed's stations here)
    inject_lat: np.ndarray | None = field(default=None, repr=False)
    inject_lon: np.ndarray | None = field(default=None, repr=False)
    inject_capacity: np.ndarray | None = field(default=None, repr=False)
    inject_role: np.ndarray | None = field(default=None, repr=False)


def _pairwise_km(lat, lon):
    la, lo = np.radians(lat), np.radians(lon)
    dla, dlo = la[:, None] - la[None, :], lo[:, None] - lo[None, :]
    a = np.sin(dla / 2) ** 2 + np.cos(la)[:, None] * np.cos(la)[None, :] * np.sin(dlo / 2) ** 2
    return 6371.0 * 2 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def simulate_city_flows(cfg: SimConfig | None = None, *, return_extras: bool = False):
    if cfg is None:
        cfg = SimConfig()
    rng = np.random.default_rng(cfg.seed)
    deg = 1.0 / 111.0
    clat, clon = cfg.center

    # ===================== Phase 1: geography, roles, topography, gravity =====================
    if cfg.inject_lat is not None:  # real geometry (compiler)
        lat = np.asarray(cfg.inject_lat, float)
        lon = np.asarray(cfg.inject_lon, float)
        n = lat.size
        capacity = np.asarray(cfg.inject_capacity, float)
        role = np.asarray(cfg.inject_role, int)
        member = np.zeros(n, int)
    else:  # synthetic clustered geometry
        n = cfg.n_stations
        cl = np.column_stack(
            [
                clat + rng.normal(0, cfg.spread_km * deg, cfg.n_clusters),
                clon + rng.normal(0, cfg.spread_km * deg, cfg.n_clusters),
            ]
        )
        member = rng.integers(0, cfg.n_clusters, n)
        lat = cl[member, 0] + rng.normal(0, 0.25 * cfg.spread_km * deg, n)
        lon = cl[member, 1] + rng.normal(0, 0.25 * cfg.spread_km * deg, n)
        capacity = rng.choice(np.array([15, 20, 25, 30]), size=n).astype(float)
        role = rng.choice(len(_ROLES), size=n, p=np.asarray(cfg.role_mix) / sum(cfg.role_mix))
    altitude = rng.normal(0, 1, n)  # Z_i
    # heavy-tailed station mass (gravity mass term): a few mega-hubs concentrate the flows so the
    # busiest 20% of stations carry ~80% of trips, like real systems. Static, so it is a multiplier.
    station_mass = np.exp(rng.normal(0, cfg.mass_tail, n))
    station_mass /= station_mass.mean()

    D = _pairwise_km(lat, lon)
    per_hour = pd.Timedelta("1h") / pd.Timedelta(f"{cfg.internal_minutes}min")
    t_travel = np.maximum(1, np.round(D / cfg.speed_kmh * per_hour).astype(int))
    uniq_tt = np.unique(t_travel)

    gravity = np.exp(-D / cfg.beta_km)
    # AXIS 2 (topography), Phase-1 only: uphill is "perceived" as farther. Static (N,N), no loop cost.
    climb = np.maximum(altitude[None, :] - altitude[:, None], 0.0)  # >0 when destination higher
    gravity = gravity * np.exp(-cfg.climb_penalty * climb * float(cfg.topography))
    np.fill_diagonal(gravity, 0.0)
    if cfg.max_trip_km is not None:
        gravity[cfg.max_trip_km <= D] = 0.0  # structural OD sparsity

    # ---- temporal profiles, incl. the two hub pulse trains (precomputed, indexed by role) ----
    isteps = int(round(cfg.days * 24 * per_hour))
    igrid = pd.date_range("2026-06-01", periods=isteps, freq=f"{cfg.internal_minutes}min", tz="UTC")
    hod = igrid.hour.to_numpy() + igrid.minute.to_numpy() / 60.0
    minute = np.arange(isteps) * cfg.internal_minutes
    am = np.exp(-((hod - 8) ** 2) / (2 * 2.5**2))
    pm = np.exp(-((hod - 18) ** 2) / (2 * 2.5**2))
    rush = am + pm
    # AXIS 1 (multimodality): heavy = big, rare pulses in rush; light = small, frequent, all day
    heavy = (minute % cfg.heavy_period_min < cfg.internal_minutes) * cfg.heavy_spike * rush
    light = (minute % cfg.light_period_min < cfg.internal_minutes) * cfg.light_spike * (0.4 + rush)
    out_profile = np.vstack([am, pm, heavy + 0.3 * pm, light])  # (4 roles, T)
    att_profile = np.vstack([pm, am, 0.5 + 0.5 * heavy, 0.4 + light])

    # AXIS 4 (weather): a multiplier time series, 1 normally, weather_drop during downpours
    weather = np.ones(isteps)
    wlen = int(round(cfg.weather_len_min / cfg.internal_minutes))
    for _ in range(cfg.weather_events):
        s = rng.integers(0, max(isteps - wlen, 1))
        weather[s : s + wlen] = cfg.weather_drop

    # AXIS 3a (ghost bikes): split virtual capacity from operating capacity, in Phase 1
    ghost = np.rint(cfg.ghost_rate * capacity)  # unrentable, always docked
    op_cap = np.maximum(capacity - ghost, 1.0)  # rentable dock budget

    # ===================== Phase 2: the engine (single loop over t) =====================
    op_bikes = 0.5 * op_cap  # rentable fluid
    total0 = op_bikes.sum()
    pending = np.zeros((isteps + int(uniq_tt.max()) + 1, n))
    occ = np.empty((isteps, n))  # reported occupancy (with ghost)
    od_agg = np.zeros((n, n))
    rate = cfg.trip_rate / per_hour
    target = 0.5 * op_cap

    for t in range(isteps):
        # demand via gathered role profiles; weather multiplier kills departures instantly
        out_prop = rate * (out_profile[role, t] + cfg.base_demand) * station_mass * weather[t]
        attract = (att_profile[role, t] + cfg.base_demand) * station_mass
        K = gravity * attract[None, :]
        K /= K.sum(axis=1, keepdims=True) + 1e-12
        desired = rng.poisson(out_prop[:, None] * K)
        # departure censoring on OPERATING bikes only (ghosts can never leave)
        out_demand = desired.sum(axis=1)
        actual_out = np.minimum(out_demand, op_bikes)
        realised = desired * (actual_out / np.maximum(out_demand, 1))[:, None]
        op_bikes = op_bikes - actual_out
        od_agg += realised
        # routing + transit buffer (arrivals delayed by travel time; weather does not stop them)
        for tt in uniq_tt:
            pending[t + tt] += (realised * (t_travel == tt)).sum(axis=0)
        # arrival censoring on operating capacity; rejected re-docked elsewhere (mass conserved)
        incoming = pending[t]
        actual_in = np.minimum(incoming, op_cap - op_bikes)
        rejected = (incoming - actual_in).sum()
        op_bikes = op_bikes + actual_in
        if rejected > 1e-9:
            free = np.maximum(op_cap - op_bikes, 0)
            if free.sum() > 0:
                op_bikes = op_bikes + rejected * free / free.sum()
        # nightly rebalancing truck, vectorised and mass-conserving: move surplus -> deficit, total
        # moved = strength * min(surplus, deficit). A real TSP route is not vectorisable; this is
        # its conservative aggregate (bikes taken from full stations are docked at empty ones).
        if cfg.rebalancing and int(round(hod[t])) == cfg.rebalancing_hour:
            dev = op_bikes - target
            surplus = np.maximum(dev, 0.0)
            deficit = np.maximum(-dev, 0.0)
            move = cfg.rebalancing_strength * min(surplus.sum(), deficit.sum())
            if surplus.sum() > 0 and deficit.sum() > 0:
                op_bikes = (
                    op_bikes - surplus / surplus.sum() * move + deficit / deficit.sum() * move
                )
        op_bikes = np.clip(op_bikes, 0.0, op_cap)
        occ[t] = (op_bikes + ghost) / capacity  # API reports ghosts as present

    # ===================== resample + canonical frames + scraper NaNs =====================
    k = max(int(round(pd.Timedelta(cfg.freq) / pd.Timedelta(f"{cfg.internal_minutes}min"))), 1)
    sel = np.arange(0, isteps, k)
    occ_out, grid, steps = occ[sel], igrid[sel], len(sel)
    bm = np.clip(np.rint(occ_out * capacity[None, :]), 0, capacity[None, :]).astype(float)

    # AXIS 3b (scraper failures), post-processing on the observed panel only (dynamics untouched)
    if cfg.scraper_cell_nan > 0:
        bm[rng.random(bm.shape) < cfg.scraper_cell_nan] = np.nan
    for _ in range(cfg.scraper_station_outages):
        s_idx = rng.integers(0, n)
        a = rng.integers(0, max(steps - 8, 1))
        bm[a : a + rng.integers(2, 8), s_idx] = np.nan

    station_id = np.array([f"S{i:04d}" for i in range(n)])
    info = pd.DataFrame(
        {
            "system_id": "synthetic",
            "station_id": station_id,
            "name": [f"Station {i} ({_ROLES[role[i]]})" for i in range(n)],
            "lat": lat,
            "lon": lon,
            "capacity": capacity.astype(int),
            "role": np.array(_ROLES)[role],
            "altitude": altitude,
            "ghost_bikes": ghost.astype(int),
            "station_type": "station",
            "is_virtual_station": False,
            "region_id": member.astype(str),
        }
    )
    status = pd.DataFrame(
        {
            "system_id": "synthetic",
            "station_id": np.tile(station_id, steps),
            "num_bikes_available": bm.reshape(-1),
            "num_docks_available": (capacity[None, :] - np.nan_to_num(bm, nan=0)).reshape(-1),
            "is_renting": 1,
            "is_returning": 1,
            "is_installed": 1,
            "last_reported": np.repeat(np.asarray(grid.view("int64")) // 1_000_000_000, n),
            "fetched_at": np.repeat(grid.to_numpy(), n),
            "gbfs_version": "2.3",
        }
    )
    if return_extras:
        in_transit = pending[isteps:].sum()
        extras = {
            "od_aggregate": od_agg,
            "distance_km": D,
            "altitude": altitude,
            "mass_conservation_error": float(abs(op_bikes.sum() + in_transit - total0) / total0),
        }
        return info, status, extras
    return info, status

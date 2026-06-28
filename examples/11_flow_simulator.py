"""Simulate a bike-share city from the bottom up, fingerprint it, and fit a digital twin.

`simulate_city_flows` generates occupancy from a mass-conserving gravity origin-destination flow,
so the true OD is known. `compute_footprint` summarises a feed as (turnover, ACF1, stockout), and
`calibrate_city` grid-searches simulator hyperparameters until the synthetic footprint matches a
real one. Here we use a simulated city as the stand-in "real feed" so the example is self-contained.
"""

import gbfs_toolkit as gb

# --- a "real" city (stand-in for a scraped feed): we will pretend we do not know its parameters
real_cfg = gb.SimConfig(
    n_stations=120, days=5, beta_km=2.0, base_demand=0.4, trip_rate=10.0, seed=7
)
info, status = gb.simulate_city_flows(real_cfg)
target = gb.compute_footprint(status)
print(
    f"real footprint: turnover={target[0]:.2f}/day  acf1={target[1]:.3f}  stockout={target[2]:.3f}"
)

# --- compile a digital twin: fit beta_km / base_demand / trip_rate to that footprint
twin = gb.calibrate_city(info, target, days=3)
print(f"calibrated twin: {twin['best_params']}  (MSE to real = {twin['mse']:.4f})")

# --- the twin is a SimConfig on the real geometry; degrade it to stress an algorithm
chaos = twin["best_config"]
chaos.days, chaos.ghost_rate, chaos.scraper_cell_nan, chaos.weather_events = 7, 0.08, 0.03, 4
_, dirty = gb.simulate_city_flows(chaos)
print(
    f"stress twin: {dirty['station_id'].nunique()} stations, {len(dirty)} rows with ghost bikes, "
    "scraper gaps and weather shocks, ready for benchmarking."
)

"""Contextualise a feed with transit and weather, the regression-ready way.

Self-contained (bundled stations + synthetic GTFS stops and a weather series, no
network):

    python 09_contextualize.py

The most time-consuming task before a mobility regression is assembling the
covariates without a temporal leak. This tags each station with nearby heavy
transit (first/last-mile feeder evidence), as-of-joins an exogenous weather series
onto the availability panel (no look-ahead), and reads the autocorrelation that a
model must respect. Bring your own GTFS and weather frames (BYOD).
"""

import numpy as np
import pandas as pd

import gbfs_toolkit as gb


def main() -> None:
    info, _status = gb.load_example()

    # 1. First/last-mile evidence: stations within 200 m of a heavy transit stop.
    #    BYOD: a GTFS `stops.txt` would supply these lat/lon.
    stops = pd.DataFrame(
        {
            "stop_id": ["metro_A", "rail_B"],
            "lat": [info["lat"].iloc[0] + 0.0005, info["lat"].iloc[-1] - 0.0003],
            "lon": [info["lon"].iloc[0], info["lon"].iloc[-1]],
        }
    )
    linked = gb.link_transit_stops(info, stops, radius_m=200)
    near = [c for c in linked.columns if "transit" in c or "stop" in c]
    print("Stations linked to transit (new columns):", near)
    print(linked[["station_id", *near]].head().to_string(index=False), "\n")

    # 2. As-of join an exogenous weather series onto an availability panel (no leak).
    times = pd.date_range("2026-06-01T06:00Z", periods=12, freq="1h")
    panel = pd.DataFrame(
        {
            "system_id": "s",
            "station_id": "a",
            "fetched_at": times,
            "num_bikes_available": (10 + 5 * np.sin(np.arange(12) / 2)).round().astype(int),
        }
    )
    weather = pd.DataFrame(
        {
            "time": pd.date_range("2026-06-01T06:00Z", periods=12, freq="1h"),
            "temp_c": np.linspace(14, 26, 12),
            "rain_mm": [0, 0, 0, 1, 2, 0, 0, 0, 0, 0, 3, 1],
        }
    )
    enriched = gb.join_exogenous_timeseries(panel, weather, exo_time="time", tolerance="1h")
    print("Panel with weather covariates (as-of, no look-ahead):")
    print(
        enriched[["fetched_at", "num_bikes_available", "temp_c", "rain_mm"]]
        .head()
        .to_string(index=False),
        "\n",
    )

    # 3. The autocorrelation a model must respect (here at 1 h and 2 h lags).
    print("Temporal autocorrelation of availability:")
    print(
        gb.temporal_autocorrelation(panel, lags=(1, 2), freq="1h").round(3).to_string(index=False)
    )


if __name__ == "__main__":
    main()

"""A ``.gbfs`` pandas DataFrame accessor for fluent method chaining.

The library's functions stay pure (``f(df, ...)``); this registers a thin namespace so the
same operations also read as ``df.gbfs.audit()``. Single-frame operations map directly;
operations that need a *second* frame (join info+status, reconcile against vehicles, …) take
it as an argument, so ``info.gbfs.join_status(status)`` reads left-to-right.

Importing :mod:`gbfs_toolkit` registers the accessor as a side effect.
"""

from __future__ import annotations

import pandas as pd

from gbfs_toolkit import audit
from gbfs_toolkit.analytics import analysis, fleet, metrics, stats
from gbfs_toolkit.core import models
from gbfs_toolkit.io import timeseries
from gbfs_toolkit.spatial import geometry as geo


@pd.api.extensions.register_dataframe_accessor("gbfs")
class GBFSAccessor:
    """Fluent access to gbfs-toolkit operations, e.g. ``df.gbfs.occupancy()``."""

    def __init__(self, pandas_obj: pd.DataFrame) -> None:
        self._df = pandas_obj

    # -- single-frame operations (map directly) -----------------------------
    def audit(self) -> pd.DataFrame:
        return audit.audit_static(self._df)

    def audit_dynamic(self, **kw) -> pd.DataFrame:
        return audit.audit_dynamic(self._df, **kw)

    def drop_flagged(self) -> pd.DataFrame:
        return audit.drop_flagged(self._df)

    def occupancy(self) -> pd.Series:
        return analysis.occupancy(self._df)

    def station_state(self) -> pd.Series:
        return analysis.station_state(self._df)

    def net_flow(self) -> pd.DataFrame:
        return timeseries.calculate_net_flow(self._df)

    def turnover(self, **kw) -> pd.DataFrame:
        return timeseries.turnover(self._df, **kw)

    def flow_balance(self) -> pd.DataFrame:
        return timeseries.flow_balance(self._df)

    def stockout_episodes(self, **kw) -> pd.DataFrame:
        return timeseries.stockout_episodes(self._df, **kw)

    def coverage_report(self, **kw) -> pd.DataFrame:
        return timeseries.coverage_report(self._df, **kw)

    def detect_frozen_stations(self, **kw) -> pd.DataFrame:
        return timeseries.detect_frozen_stations(self._df, **kw)

    def system_profile(self) -> pd.Series:
        return stats.system_profile(self._df)

    def concentration_metrics(self, **kw) -> pd.Series:
        return stats.concentration_metrics(self._df, **kw)

    def coverage_stats(self, **kw) -> pd.Series:
        return stats.coverage_stats(self._df, **kw)

    def availability_stats(self, **kw) -> pd.DataFrame:
        return stats.availability_stats(self._df, **kw)

    def morans_i(self, value_col: str, **kw) -> pd.Series:
        return stats.morans_i(self._df, value_col, **kw)

    def to_gdf(self, **kw):
        return geo.to_gdf(self._df, **kw)

    def to_geojson(self, **kw):
        return geo.to_geojson(self._df, **kw)

    def validate(self, schema: str) -> pd.DataFrame:
        return models.validate_schema(self._df, schema)

    def coerce(self, schema: str) -> pd.DataFrame:
        return models.coerce_schema(self._df, schema)

    # -- operations needing a second frame (passed as the argument) ---------
    def join_status(self, status: pd.DataFrame) -> pd.DataFrame:
        """``info.gbfs.join_status(status)`` → analysis-ready availability frame."""
        return analysis.join_availability(self._df, status)

    def audit_frames(self, status: pd.DataFrame | None = None, **kw) -> pd.DataFrame:
        return audit.audit_frames(self._df, status, **kw)

    def join_vehicle_types(self, vehicle_types: pd.DataFrame) -> pd.DataFrame:
        return analysis.join_vehicle_types(self._df, vehicle_types)

    def join_pricing(self, plans: pd.DataFrame) -> pd.DataFrame:
        return analysis.join_pricing(self._df, plans)

    def ebikes(self, vehicle_types: pd.DataFrame) -> pd.DataFrame:
        return analysis.ebikes(self._df, vehicle_types)

    def network_changes(self, new: pd.DataFrame, **kw) -> pd.DataFrame:
        """``old.gbfs.network_changes(new)`` → added/removed/recapacitated/moved."""
        return analysis.network_changes(self._df, new, **kw)

    # -- research indicators (1.3.0), single-frame --------------------------
    def service_reliability_index(self, **kw) -> pd.DataFrame:
        return metrics.service_reliability_index(self._df, **kw)

    def station_outage_rates(self) -> pd.DataFrame:
        return metrics.station_outage_rates(self._df)

    def flow_asymmetry_ratio(self, **kw) -> pd.DataFrame:
        return metrics.flow_asymmetry_ratio(self._df, **kw)

    def fleet_turnover_proxy(self, **kw) -> pd.DataFrame:
        return metrics.fleet_turnover_proxy(self._df, **kw)

    def cumulative_imbalance(self, **kw) -> pd.DataFrame:
        return metrics.cumulative_imbalance(self._df, **kw)

    def docking_pressure(self) -> pd.DataFrame:
        return metrics.docking_pressure(self._df)

    def temporal_autocorrelation(self, **kw) -> pd.DataFrame:
        return metrics.temporal_autocorrelation(self._df, **kw)

    def aliasing_vulnerability(self) -> pd.DataFrame:
        return metrics.aliasing_vulnerability(self._df)

    def dynamic_gini_index(self, **kw) -> pd.DataFrame:
        return metrics.dynamic_gini_index(self._df, **kw)

    def spatial_center_of_mass(self, **kw) -> pd.DataFrame:
        return metrics.spatial_center_of_mass(self._df, **kw)

    def spatial_entropy(self, **kw) -> pd.DataFrame:
        return metrics.spatial_entropy(self._df, **kw)

    def diurnal_summary_stats(self, **kw) -> pd.DataFrame:
        return metrics.diurnal_summary_stats(self._df, **kw)

    def temporal_context_features(self, **kw) -> pd.DataFrame:
        return analysis.temporal_context_features(self._df, **kw)

    def vehicle_idle_time(self, **kw) -> pd.DataFrame:
        return fleet.vehicle_idle_time(self._df, **kw)

    # -- research indicators (1.3.0), needing a second frame ----------------
    def capacity_utilization(self, info: pd.DataFrame) -> pd.DataFrame:
        return analysis.capacity_utilization(self._df, info)

    def two_step_fca(self, demand: pd.DataFrame, **kw) -> pd.Series:
        return geo.two_step_fca(self._df, demand, **kw)

    def join_exogenous(self, exogenous: pd.DataFrame, **kw) -> pd.DataFrame:
        return metrics.join_exogenous_timeseries(self._df, exogenous, **kw)

    # -- advanced analytics (1.4.0) -----------------------------------------
    def local_morans_i(self, value_col: str, **kw) -> pd.DataFrame:
        return metrics.local_morans_i(self._df, value_col, **kw)

    def diurnal_bimodality(self, **kw) -> pd.DataFrame:
        return metrics.diurnal_bimodality(self._df, **kw)

    def availability_synchrony(self, **kw) -> pd.DataFrame:
        return metrics.availability_synchrony(self._df, **kw)

    def outage_survival(self, **kw) -> pd.DataFrame:
        return metrics.outage_survival(self._df, **kw)

    def temporal_concentration(self, **kw) -> pd.DataFrame:
        return metrics.temporal_concentration(self._df, **kw)

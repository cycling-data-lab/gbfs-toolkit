"""A ``.gbfs`` pandas DataFrame accessor for fluent method chaining.

The library's functions stay pure (``f(df, ...)``); this registers a thin namespace so the
same operations also read as ``df.gbfs.audit()``. Single-frame operations map directly;
operations that need a *second* frame (join info+status, reconcile against vehicles, …) take
it as an argument — so ``info.gbfs.join_status(status)`` reads left-to-right.

Importing :mod:`gbfs_toolkit` registers the accessor as a side effect.
"""

from __future__ import annotations

import pandas as pd

from gbfs_toolkit import analysis, audit, geo, models, stats, timeseries


@pd.api.extensions.register_dataframe_accessor("gbfs")
class GBFSAccessor:
    """Fluent access to gbfs-toolkit operations — e.g. ``df.gbfs.occupancy()``."""

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

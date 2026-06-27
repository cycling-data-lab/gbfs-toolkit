"""gbfs-toolkit — research-grade ingestion + semantic quality audit for GBFS feeds.

The community's :mod:`gbfs-validator` checks that a feed is *syntactically* valid;
this package checks whether it is *semantically* trustworthy and analysis-ready —
the A1–A7 taxonomy of Fossé & Pallares — and normalises feeds into a stable,
version-independent data model you can reuse across studies.

Quick start
-----------

    >>> import json, gbfs_toolkit as gb
    >>> raw = json.load(open("station_information.json"))
    >>> stations = gb.to_canonical_station_info(raw, system_id="velib")
    >>> verdict = gb.audit_static(stations)
    >>> clean = stations[~verdict["flagged"].to_numpy()]
"""

from gbfs_toolkit import models
from gbfs_toolkit.audit import audit_static
from gbfs_toolkit.catalog import resolve, systems_catalog
from gbfs_toolkit.models import AUDIT_FLAGS, RULES, SchemaError
from gbfs_toolkit.normalize import to_canonical_station_info

__version__ = "0.1.0"

__all__ = [
    "audit_static",
    "to_canonical_station_info",
    "systems_catalog",
    "resolve",
    "models",
    "RULES",
    "AUDIT_FLAGS",
    "SchemaError",
    "__version__",
]

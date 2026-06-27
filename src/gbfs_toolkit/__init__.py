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
from gbfs_toolkit.fetch import GBFSFeed, audit_feed, availability, parse_discovery
from gbfs_toolkit.models import AUDIT_FLAGS, RULES, SchemaError
from gbfs_toolkit.normalize import (
    to_canonical_station_info,
    to_canonical_station_status,
    to_canonical_vehicles,
)

__version__ = "0.1.0"

__all__ = [
    # audit
    "audit_static",
    "audit_feed",
    # fetch / scrape (daily drivers)
    "GBFSFeed",
    "availability",
    "parse_discovery",
    # normalise
    "to_canonical_station_info",
    "to_canonical_station_status",
    "to_canonical_vehicles",
    # catalogue
    "systems_catalog",
    "resolve",
    # meta
    "models",
    "RULES",
    "AUDIT_FLAGS",
    "SchemaError",
    "__version__",
]

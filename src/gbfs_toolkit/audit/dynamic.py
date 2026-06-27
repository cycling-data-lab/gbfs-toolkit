"""Dynamic semantic audit: logic checks on live availability payloads.

Where the static audit (A1–A7) inspects the inventory, the dynamic audit inspects
the *real-time* numbers, which break constantly in ways a syntactic validator never
sees: negative counts, bikes+docks exceeding capacity, and stale feeds.
"""

from __future__ import annotations

import pandas as pd

from gbfs_toolkit.core.models import require_columns

#: Dynamic check flags.
DYNAMIC_FLAGS = ("D1_negative", "D2_over_capacity", "D3_stale")

_REQUIRED = ["station_id", "num_bikes_available", "num_docks_available"]


def audit_dynamic(
    availability: pd.DataFrame,
    *,
    ttl_seconds: float | None = None,
    stale_after_minutes: float = 60.0,
    buffer_seconds: float = 60.0,
) -> pd.DataFrame:
    """Logic checks on a live availability frame.

    Parameters
    ----------
    availability : pandas.DataFrame
        A status frame (ideally joined with info for ``capacity``); requires
        ``station_id, num_bikes_available, num_docks_available``. Uses
        ``capacity`` and the UTC timestamps ``last_reported`` / ``fetched_at``
        when present.
    ttl_seconds : float, optional
        The feed's advertised TTL. When given, staleness is
        ``fetched_at − last_reported > ttl_seconds + buffer_seconds`` (the correct,
        feed-specific rule; pass ``GBFSFeed.ttl``). Falls back to
        ``stale_after_minutes`` otherwise.
    stale_after_minutes : float, default 60
        Fallback staleness window when ``ttl_seconds`` is not provided.
    buffer_seconds : float, default 60
        Grace period added to ``ttl_seconds`` (clock skew / fetch latency).

    Returns
    -------
    pandas.DataFrame
        ``station_id``, ``D1_negative``, ``D2_over_capacity``, ``D3_stale``,
        ``flagged`` and a human-readable ``reason``.
    """
    require_columns(availability, _REQUIRED, what="audit_dynamic")
    df = availability.reset_index(drop=True)
    bikes = pd.to_numeric(df["num_bikes_available"], errors="coerce")
    docks = pd.to_numeric(df["num_docks_available"], errors="coerce")

    out = pd.DataFrame({"station_id": df["station_id"]})
    out["D1_negative"] = (bikes < 0) | (docks < 0)

    if "capacity" in df:
        cap = pd.to_numeric(df["capacity"], errors="coerce")
        # only meaningful where capacity is a positive number
        out["D2_over_capacity"] = (bikes.fillna(0) + docks.fillna(0) > cap) & (cap > 0)
    else:
        out["D2_over_capacity"] = False

    if ttl_seconds is not None:
        threshold = pd.Timedelta(seconds=ttl_seconds + buffer_seconds)
        stale_label = f"stale (> ttl {ttl_seconds:g}s + {buffer_seconds:g}s)"
    else:
        threshold = pd.Timedelta(minutes=stale_after_minutes)
        stale_label = f"stale (> {stale_after_minutes:g} min)"

    if "last_reported" in df and "fetched_at" in df:
        lag = pd.to_datetime(df["fetched_at"], utc=True, errors="coerce") - pd.to_datetime(
            df["last_reported"], utc=True, errors="coerce"
        )
        out["D3_stale"] = lag > threshold
    else:
        out["D3_stale"] = False

    out[list(DYNAMIC_FLAGS)] = out[list(DYNAMIC_FLAGS)].fillna(False).astype(bool)
    flags = out[list(DYNAMIC_FLAGS)].to_numpy()
    labels = {
        "D1_negative": "negative count",
        "D2_over_capacity": "bikes+docks > capacity",
        "D3_stale": stale_label,
    }
    out["flagged"] = flags.any(axis=1)
    out["reason"] = [
        ", ".join(labels[f] for f, fired in zip(DYNAMIC_FLAGS, row, strict=True) if fired)
        for row in flags
    ]
    return out

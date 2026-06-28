"""Exception hierarchy, so orchestrators can catch and react precisely.

A single base ([`GBFSError`][gbfs_toolkit.GBFSError]) lets a scraper ``except GBFSError`` to catch anything
this library raises, while the specific subclasses let it branch (retry a fetch, skip a
not-modified feed, surface a schema problem). [`SchemaError`][gbfs_toolkit.SchemaError] lives in
[`models`][gbfs_toolkit.models] for backward compatibility but subclasses
[`GBFSValidationError`][gbfs_toolkit.GBFSValidationError].
"""

from __future__ import annotations


class GBFSError(Exception):
    """Base class for every error raised by gbfs-toolkit.

    See Also
    --------
    [`GBFSFetchError`][gbfs_toolkit.GBFSFetchError] : Network/fetch failures.
    [`GBFSValidationError`][gbfs_toolkit.GBFSValidationError] : Schema/validation failures.
    [`GBFSDiscoveryError`][gbfs_toolkit.GBFSDiscoveryError] : Discovery-document failures.
    """


class GBFSFetchError(GBFSError):
    """A network fetch failed (HTTP error, timeout, unreachable host).

    See Also
    --------
    [`GBFSError`][gbfs_toolkit.GBFSError] : The base error.
    [`GBFSNotModified`][gbfs_toolkit.GBFSNotModified] : The not-modified signal.
    """


class GBFSDiscoveryError(GBFSError, KeyError):
    """A ``gbfs.json`` could not be parsed, or a required feed is absent.

    Also subclasses `KeyError` (a missing feed *is* a missing key) for backward
    compatibility: ``except KeyError`` and ``except GBFSError`` both catch it.

    See Also
    --------
    [`GBFSError`][gbfs_toolkit.GBFSError] : The base error.
    """


class GBFSValidationError(GBFSError):
    """Data does not satisfy the canonical schema or a documented invariant.

    See Also
    --------
    [`GBFSError`][gbfs_toolkit.GBFSError] : The base error.
    [`SchemaError`][gbfs_toolkit.SchemaError] : The lower-level schema error.
    """


class GBFSNotModified(GBFSError):  # noqa: N818 (a control-flow signal, not an error condition)
    """The server answered HTTP 304 Not Modified; skip re-ingesting this snapshot.

    See Also
    --------
    [`GBFSError`][gbfs_toolkit.GBFSError] : The base error.
    [`GBFSFetchError`][gbfs_toolkit.GBFSFetchError] : The general fetch error.
    """

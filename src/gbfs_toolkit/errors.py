"""Exception hierarchy, so orchestrators can catch and react precisely.

A single base (:class:`GBFSError`) lets a scraper ``except GBFSError`` to catch anything
this library raises, while the specific subclasses let it branch (retry a fetch, skip a
not-modified feed, surface a schema problem). :class:`SchemaError` lives in
:mod:`gbfs_toolkit.models` for backward compatibility but subclasses
:class:`GBFSValidationError`.
"""

from __future__ import annotations


class GBFSError(Exception):
    """Base class for every error raised by gbfs-toolkit."""


class GBFSFetchError(GBFSError):
    """A network fetch failed (HTTP error, timeout, unreachable host)."""


class GBFSDiscoveryError(GBFSError, KeyError):
    """A ``gbfs.json`` could not be parsed, or a required feed is absent.

    Also subclasses :class:`KeyError` (a missing feed *is* a missing key) for backward
    compatibility: ``except KeyError`` and ``except GBFSError`` both catch it.
    """


class GBFSValidationError(GBFSError):
    """Data does not satisfy the canonical schema or a documented invariant."""


class GBFSNotModified(GBFSError):  # noqa: N818 (a control-flow signal, not an error condition)
    """The server answered HTTP 304 Not Modified; skip re-ingesting this snapshot."""

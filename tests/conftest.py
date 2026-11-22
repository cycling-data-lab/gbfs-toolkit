"""Shared test configuration.

Enable pandas Copy-on-Write for the whole test run. Under CoW a function that silently
mutates a slice of an input frame raises instead of corrupting the caller's data, which
turns the "no in-place mutation" contract (see test_input_purity) into a hard guarantee
across every test, not just the ones that check it explicitly.

pandas 3 always uses Copy-on-Write and deprecates the option, so it is only set on 2.x.

Tests marked ``network`` reach live GBFS endpoints. They are skipped unless the run
passes ``--run-network`` (or sets ``GBFS_TOOLKIT_NETWORK_TESTS=1``), so the default suite
is offline and deterministic.
"""

from __future__ import annotations

import os

import pandas as pd
import pytest

if int(pd.__version__.split(".", 1)[0]) < 3:
    pd.options.mode.copy_on_write = True


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-network",
        action="store_true",
        default=False,
        help="run the tests marked `network` (they reach live GBFS endpoints)",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--run-network") or os.environ.get("GBFS_TOOLKIT_NETWORK_TESTS") == "1":
        return
    skip = pytest.mark.skip(reason="network test: pass --run-network to run it")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip)


_LOOPBACK = {"127.0.0.1", "::1", "localhost"}


@pytest.fixture(autouse=True)
def _offline_unless_marked(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):
    """Make an accidental live request fail loudly in a test not marked ``network``."""
    if "network" in request.keywords:
        yield
        return
    import socket

    real_connect = socket.socket.connect

    def guarded_connect(self, address):
        host = address[0] if isinstance(address, tuple) else None
        if host is not None and host not in _LOOPBACK:
            raise RuntimeError(
                f"test tried to reach {address!r}; mark it `network` or use a fake get_json"
            )
        return real_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    yield

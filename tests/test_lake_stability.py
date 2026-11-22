"""The data-lake modules are public, documented as experimental, import lightly and never print."""

from __future__ import annotations

import importlib
import inspect
import subprocess
import sys

import pytest

from gbfs_toolkit._stability import EXPERIMENTAL_MODULES

MODULES = sorted(EXPERIMENTAL_MODULES)


@pytest.mark.parametrize("name", MODULES)
def test_each_module_declares_all_and_the_experimental_note(name):
    mod = importlib.import_module(name)
    assert mod.__all__ and all(hasattr(mod, n) for n in mod.__all__)
    assert '!!! warning "Experimental"' in (mod.__doc__ or ""), (
        f"{name} lacks its Experimental note"
    )
    for n in mod.__all__:
        obj = getattr(mod, n)
        if inspect.isfunction(obj) or inspect.isclass(obj):
            assert inspect.getdoc(obj), f"{name}.{n} has no docstring"


def test_the_list_is_complete_and_modules_are_not_top_level_names():
    import gbfs_toolkit as gb

    assert len(MODULES) == 9
    for n in ("collect", "quality", "aggregate", "store", "history", "trips", "release", "repro"):
        assert f"gbfs_toolkit.{n}" in EXPERIMENTAL_MODULES
        assert n not in gb.__all__  # experimental modules are imported by path, not re-exported


def test_importing_the_package_does_not_import_the_lake_modules_or_optional_dependencies():
    code = (
        "import sys, gbfs_toolkit; "
        "bad = [m for m in ('gbfs_toolkit.collect', 'gbfs_toolkit.release', 'gbfs_toolkit.store', "
        "'duckdb', 'requests') if m in sys.modules]; "
        "assert not bad, bad"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_lake_modules_import_without_pyarrow_installed():
    """Parquet is an extra: the modules import, and the functions that need it say so."""
    code = (
        "import sys; sys.modules['pyarrow'] = None; "
        "import gbfs_toolkit.collect, gbfs_toolkit.quality, gbfs_toolkit.aggregate, gbfs_toolkit.store, "
        "gbfs_toolkit.history, gbfs_toolkit.trips, gbfs_toolkit.release, gbfs_toolkit.repro, "
        "gbfs_toolkit.stations.match; "
        "import pandas as pd\n"
        "from gbfs_toolkit.store import write_lake\n"
        "try:\n"
        "    write_lake(pd.DataFrame({'system_id': ['a'], 'observed_at_utc': pd.to_datetime(['2026-01-01'], utc=True)}), '/tmp/x-nolake')\n"
        "except ImportError as e:\n"
        "    assert 'gbfs-toolkit[parquet]' in str(e)\n"
        "else:\n"
        "    raise SystemExit('no ImportError')\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True)

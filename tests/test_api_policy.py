"""The API policy (docs/api-policy.md) as executable checks."""

from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
import warnings

import pytest

import gbfs_toolkit as gb
from gbfs_toolkit._stability import EXPERIMENTAL
from gbfs_toolkit.core import errors
from gbfs_toolkit.core.models import SchemaError
from gbfs_toolkit.core.utils import deprecated, warn_deprecated


def _modules():
    for info in pkgutil.walk_packages(gb.__path__, "gbfs_toolkit."):
        if info.name.rsplit(".", 1)[-1].startswith("_"):
            continue
        yield importlib.import_module(info.name)


MODULES = [m for m in _modules() if not hasattr(m, "__path__")]  # leaf modules, not packages


@pytest.mark.parametrize("mod", MODULES, ids=lambda m: m.__name__)
def test_every_module_declares_all(mod):
    """Each module states its public names, and they all exist."""
    assert hasattr(mod, "__all__"), f"{mod.__name__} has no __all__"
    for name in mod.__all__:
        assert hasattr(mod, name), f"{mod.__name__}.__all__ lists missing {name!r}"


def test_top_level_names_come_from_declared_submodule_names():
    """What the package re-exports is declared public by the module that defines it."""
    for name in gb.__all__:
        obj = getattr(gb, name)
        mod = inspect.getmodule(obj)
        if mod is None or not mod.__name__.startswith("gbfs_toolkit."):
            continue
        declared = getattr(mod, "__all__", None)
        if declared is None or not (inspect.isfunction(obj) or inspect.isclass(obj)):
            continue
        assert name in declared or obj.__name__ in declared, (
            f"gbfs_toolkit.{name} is defined in {mod.__name__} but not in its __all__"
        )


def test_experimental_names_are_public_and_flagged():
    for name in sorted(EXPERIMENTAL):
        assert name in gb.__all__, f"{name} is marked experimental but is not public"
        doc = inspect.getdoc(getattr(gb, name)) or ""
        assert "Experimental" in doc, f"{name} lacks its 'Experimental' note"


def test_stable_names_are_not_flagged_experimental():
    for name in gb.__all__:
        if name in EXPERIMENTAL or name in {"SchemaError"}:
            continue
        obj = getattr(gb, name)
        doc = inspect.getdoc(obj) if callable(obj) else None
        assert not (doc and '!!! warning "Experimental"' in doc), (
            f"{name} says Experimental but is not listed in _stability.EXPERIMENTAL"
        )


# --- deprecation helpers ---------------------------------------------------------


def test_warn_deprecated_message_names_version_removal_and_replacement():
    with pytest.warns(FutureWarning) as rec:
        warn_deprecated("old", since="2.1.0", removal="3.0.0", alternative="new")
    msg = str(rec[0].message)
    assert "old" in msg and "2.1.0" in msg and "3.0.0" in msg and "new" in msg


def test_warn_deprecated_points_at_the_caller():
    def api():
        warn_deprecated("old", since="2.1.0")

    with pytest.warns(FutureWarning) as rec:
        api()
    assert rec[0].filename == __file__


def test_deprecated_decorator_keeps_behaviour_and_documents_itself():
    @deprecated(since="2.1.0", alternative="gbfs_toolkit.new")
    def old(x, *, k=1):
        """Scale x."""
        return x * k

    with pytest.warns(FutureWarning, match="deprecated since gbfs-toolkit 2.1.0"):
        assert old(3, k=2) == 6
    assert old.__name__ == "old"
    assert "Scale x." in old.__doc__ and "Deprecated" in old.__doc__


def test_no_public_function_is_deprecated_yet():
    """Nothing is deprecated in 2.0.x: a stable call must be silent."""
    with warnings.catch_warnings():
        warnings.simplefilter("error", FutureWarning)
        importlib.reload(importlib.import_module("gbfs_toolkit.core.utils"))


# --- errors ----------------------------------------------------------------------


def test_exception_hierarchy():
    for exc in (
        errors.GBFSFetchError,
        errors.GBFSDiscoveryError,
        errors.GBFSValidationError,
        errors.GBFSNotModified,
    ):
        assert issubclass(exc, errors.GBFSError)
    assert issubclass(SchemaError, errors.GBFSValidationError)
    assert issubclass(SchemaError, ValueError)


def test_missing_column_is_a_schema_error_and_still_a_keyerror():
    import pandas as pd

    with pytest.raises(SchemaError) as ei:
        gb.label_diurnal_typology(pd.DataFrame({"h00": [1.0]}))
    assert isinstance(ei.value, KeyError)
    assert isinstance(ei.value, errors.GBFSError)
    assert "h01" in str(ei.value) and not str(ei.value).startswith("'")


def test_invalid_argument_value_is_a_value_error():
    from gbfs_toolkit.core.utils import offset_minutes

    with pytest.raises(ValueError, match="fixed-width"):
        offset_minutes("1ME")  # a calendar frequency is not fixed-width


# --- logging ---------------------------------------------------------------------


def test_library_logger_has_only_a_null_handler():
    handlers = logging.getLogger("gbfs_toolkit").handlers
    assert handlers and all(isinstance(h, logging.NullHandler) for h in handlers)


def test_library_code_does_not_print(capsys):
    """Only the CLI and show_versions print; the rest goes through logging."""
    import ast
    import pathlib

    root = pathlib.Path(gb.__file__).parent
    allowed = {"interfaces/cli.py", "interfaces/diagnostics.py"}
    offenders = []
    for path in root.rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        if rel in allowed:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "print"
            ):
                offenders.append(f"{rel}:{node.lineno}")
    assert not offenders, offenders


def test_fetch_multiple_failure_is_logged_not_raised(caplog):
    import pandas as pd

    def get_json(url):
        raise gb.GBFSFetchError("boom")

    catalog = pd.DataFrame(
        {
            "system_id": ["s1"],
            "name": ["S1"],
            "location": ["Nowhere"],
            "country_code": ["XX"],
            "url": ["https://example.invalid"],
            "auto_discovery_url": ["https://example.invalid/gbfs.json"],
        }
    )
    with caplog.at_level(logging.WARNING, logger="gbfs_toolkit"):
        out = gb.fetch_multiple(["s1"], catalog=catalog, get_json=get_json, max_workers=1)
    assert isinstance(out["s1"], Exception)
    assert any("s1" in r.getMessage() for r in caplog.records)

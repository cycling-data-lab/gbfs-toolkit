"""Environment introspection — paste the output into a bug report."""

from __future__ import annotations

import platform
import sys
from importlib.metadata import PackageNotFoundError, version

_DEPS = (
    "gbfs-toolkit",
    "numpy",
    "scipy",
    "pandas",
    "pyarrow",
    "requests",
    "geopandas",
    "shapely",
    "scikit-learn",
    "tslearn",
)


def show_versions() -> None:
    """Print Python, OS and key dependency versions (the usual ``show_versions`` diagnostic)."""
    print(f"python      : {sys.version.split()[0]}")
    print(f"os          : {platform.platform()}")
    for dep in _DEPS:
        try:
            v = version(dep)
        except PackageNotFoundError:
            v = "not installed"
        print(f"{dep:<12}: {v}")

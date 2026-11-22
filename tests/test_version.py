"""One version, read from the installed metadata, and release files that agree with it.

The 2.0.0 wheel on PyPI reported ``__version__ == "1.8.0"``: the version was written in
two places (pyproject.toml and ``__init__``) and a release edit touched only one. The
module now reads the distribution metadata; these tests keep the remaining release files
(release-please manifest, CITATION.cff) on the same number.
"""

from __future__ import annotations

import importlib.metadata
import json
import re
from pathlib import Path

import gbfs_toolkit as gb

ROOT = Path(__file__).resolve().parent.parent


def _pyproject_version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    project = text.split("[project]", 1)[1].split("\n[", 1)[0]
    match = re.search(r'^version\s*=\s*"([^"]+)"', project, flags=re.MULTILINE)
    assert match, "pyproject.toml must declare a static [project] version"
    return match.group(1)


def test_version_is_the_installed_distribution_version():
    assert gb.__version__ == importlib.metadata.version("gbfs-toolkit")


def test_version_is_pep440_release():
    assert re.fullmatch(r"\d+\.\d+\.\d+((a|b|rc)\d+)?(\.post\d+)?(\.dev\d+)?", gb.__version__)


def test_init_does_not_hard_code_a_version():
    source = (ROOT / "src" / "gbfs_toolkit" / "__init__.py").read_text(encoding="utf-8")
    # release-please rewrites `__version__ = "X.Y.Z"`; there must be nothing for it to rewrite.
    assert not re.search(r'__version__ ?= ?["\']\d', source)
    assert "x-release-please-version" not in source


def test_release_files_agree_with_pyproject():
    version = _pyproject_version()
    manifest = json.loads((ROOT / ".release-please-manifest.json").read_text(encoding="utf-8"))
    assert manifest["."] == version
    citation = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
    assert re.search(rf'^version: "{re.escape(version)}"', citation, flags=re.MULTILINE)


def test_release_please_uses_one_tag_format():
    config = json.loads((ROOT / "release-please-config.json").read_text(encoding="utf-8"))
    assert config["include-component-in-tag"] is True
    assert config["packages"]["."]["component"] == "gbfs-toolkit"
    assert "src/gbfs_toolkit/__init__.py" not in config["packages"]["."].get("extra-files", [])

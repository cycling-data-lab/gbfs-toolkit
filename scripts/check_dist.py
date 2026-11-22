"""Check built distributions before they are uploaded to PyPI.

Usage::

    python scripts/check_dist.py dist/                 # version taken from pyproject.toml
    python scripts/check_dist.py dist/ --expect 2.0.1  # also pin it (e.g. from the tag)

It fails (exit 1) unless there is exactly one wheel and one sdist, both carry the
version declared in ``pyproject.toml`` (and ``--expect`` when given), the wheel ships
``py.typed`` and its METADATA declares the SPDX licence and ``Requires-Python``, and no
test, docs or benchmark file leaked into the wheel. It reads the archives only; it does
not install anything. The 2.0.0 wheel on PyPI said ``__version__ == "1.8.0"`` because
the version lived in two files; this is the gate that would have caught it.
"""

from __future__ import annotations

import argparse
import re
import sys
import tarfile
import zipfile
from email.parser import Parser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = "gbfs_toolkit"


def declared_version() -> str:
    """The ``[project] version`` of pyproject.toml (no TOML parser needed on 3.10)."""
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    project = text.split("[project]", 1)[1].split("\n[", 1)[0]
    match = re.search(r'^version\s*=\s*"([^"]+)"', project, flags=re.MULTILINE)
    if match is None:
        raise SystemExit("pyproject.toml: no static [project] version")
    return match.group(1)


def check(dist: Path, expect: str | None) -> list[str]:
    errors: list[str] = []
    version = declared_version()
    if expect is not None and expect != version:
        errors.append(f"pyproject.toml declares {version}, expected {expect}")
    wheels = sorted(dist.glob("*.whl"))
    sdists = sorted(dist.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        return [*errors, f"expected one wheel and one sdist in {dist}, got {wheels + sdists}"]
    wheel, sdist = wheels[0], sdists[0]

    with zipfile.ZipFile(wheel) as zf:
        names = zf.namelist()
        meta_name = next((n for n in names if n.endswith(".dist-info/METADATA")), None)
        if meta_name is None:
            return [*errors, f"{wheel.name}: no METADATA"]
        meta = Parser().parsestr(zf.read(meta_name).decode("utf-8"))
        init = zf.read(f"{PACKAGE}/__init__.py").decode("utf-8")
    if meta["Version"] != version:
        errors.append(f"{wheel.name}: METADATA Version {meta['Version']} != {version}")
    if f"-{version}-" not in wheel.name:
        errors.append(f"{wheel.name}: file name does not carry {version}")
    if f"{PACKAGE}/py.typed" not in names:
        errors.append(f"{wheel.name}: py.typed missing (PEP 561)")
    if meta.get("License-Expression") != "MIT":
        errors.append(f"{wheel.name}: License-Expression is {meta.get('License-Expression')!r}")
    if not meta.get("Requires-Python"):
        errors.append(f"{wheel.name}: no Requires-Python")
    if re.search(r'^__version__\s*=\s*["\']', init, flags=re.MULTILINE):
        errors.append(f"{wheel.name}: __init__.py hard-codes __version__ (must read metadata)")
    leaked = [n for n in names if n.split("/", 1)[0] in {"tests", "docs", "benchmarks"}]
    if leaked:
        errors.append(f"{wheel.name}: unexpected top-level files {leaked[:5]}")

    with tarfile.open(sdist) as tf:
        top = f"{PACKAGE.replace('_', '-')}-{version}"
        alt = f"{PACKAGE}-{version}"
        members = tf.getnames()
        pkg_info = next((m for m in members if m in (f"{top}/PKG-INFO", f"{alt}/PKG-INFO")), None)
        if pkg_info is None:
            errors.append(f"{sdist.name}: no PKG-INFO for version {version}")
        else:
            info = Parser().parsestr(tf.extractfile(pkg_info).read().decode("utf-8"))
            if info["Version"] != version:
                errors.append(f"{sdist.name}: PKG-INFO Version {info['Version']} != {version}")
        if not any(m.endswith("/LICENSE") for m in members):
            errors.append(f"{sdist.name}: LICENSE missing")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("dist", type=Path, help="directory holding the built wheel and sdist")
    parser.add_argument("--expect", help="version the distributions must carry")
    args = parser.parse_args(argv)
    expect = args.expect.removeprefix("gbfs-toolkit-").removeprefix("v") if args.expect else None
    errors = check(args.dist, expect)
    for err in errors:
        print(f"check_dist: {err}", file=sys.stderr)
    if not errors:
        print(f"check_dist: {args.dist} OK ({declared_version()})")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

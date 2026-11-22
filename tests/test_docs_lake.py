"""Every Python example of the data-lake documentation pages runs, offline, and says what it says.

The blocks of one page share a namespace and run in a scratch folder, in order. A block whose first
line is ``# not run`` is an illustration; a block that imports ``duckdb`` is skipped without it.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

pytest.importorskip("pyarrow")

DOCS = Path(__file__).resolve().parent.parent / "docs" / "lake"
ROOT_DOCS = DOCS.parent
#: The data-lake pages, the recipes and the tutorial: every Python example of them runs.
PAGES = sorted(DOCS.glob("*.md")) if DOCS.is_dir() else []
PAGES += sorted((ROOT_DOCS / "recipes").glob("*.md")) + [ROOT_DOCS / "tutorial.md"]
FENCE = re.compile(r"^```python\n(.*?)^```", re.S | re.M)


def blocks(page: Path) -> list[str]:
    return [
        b for b in FENCE.findall(page.read_text(encoding="utf-8")) if not b.startswith("# not run")
    ]


def test_every_module_has_a_page_in_the_navigation():
    nav = (DOCS.parent.parent / "mkdocs.yml").read_text(encoding="utf-8")
    names = {p.name for p in PAGES}
    assert {
        "index.md",
        "collect.md",
        "quality.md",
        "aggregate.md",
        "store.md",
        "history.md",
        "stations-match.md",
        "trips.md",
        "release.md",
        "repro.md",
        "cli.md",
    } <= names
    for page in PAGES:
        rel = page.relative_to(ROOT_DOCS).as_posix()
        assert rel in nav, f"{rel} is not in the mkdocs navigation"


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.relative_to(ROOT_DOCS).as_posix())
def test_page_examples_run(page, tmp_path, monkeypatch, capsys):
    code_blocks = blocks(page)
    has_no_code = (
        page.name == "cli.md" or page.relative_to(ROOT_DOCS).as_posix() == "recipes/index.md"
    )
    if not has_no_code:
        assert code_blocks, f"{page.name} has no runnable example"
    monkeypatch.chdir(tmp_path)
    namespace: dict = {"__name__": "docs_example"}
    for i, block in enumerate(code_blocks):
        if "import duckdb" in block and importlib.util.find_spec("duckdb") is None:
            continue
        try:
            exec(compile(block, f"{page.name}[block {i}]", "exec"), namespace)  # noqa: S102
        except Exception as exc:  # report which block of which page broke
            raise AssertionError(f"{page.name}, block {i}: {type(exc).__name__}: {exc}") from exc
    capsys.readouterr()


def test_overview_example_tells_the_truth(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    ns: dict = {}
    exec(compile(blocks(DOCS / "index.md")[0], "index.md", "exec"), ns)  # noqa: S102
    out = capsys.readouterr().out
    assert "outage_collector" in out or "partial" in out  # lakeside's six-hour hole is reported
    assert "True" in out.splitlines()[-1]  # the release verifies
    totals = [line for line in out.splitlines() if line.startswith("{'15m'")][0]
    assert len(set(eval(totals).values())) == 1  # the three levels hold the same rows

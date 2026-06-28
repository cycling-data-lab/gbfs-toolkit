"""Smoke-test the self-contained example scenarios, so the How-To snippets stay correct.

The scripts in ``examples/`` are the single source of truth for the How-To pages
(included verbatim via the ``--8<--`` snippet syntax). Running them here keeps the
documented code from drifting. Only the network-free scenarios are exercised.
"""

import runpy
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


@pytest.mark.parametrize("script", ["05_rigorous_audit.py", "06_equity_rebalancing.py"])
def test_example_scenario_runs(script):
    runpy.run_path(str(EXAMPLES / script), run_name="__main__")

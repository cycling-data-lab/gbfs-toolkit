"""Shared test configuration.

Enable pandas Copy-on-Write for the whole test run. Under CoW a function that silently
mutates a slice of an input frame raises instead of corrupting the caller's data, which
turns the "no in-place mutation" contract (see test_input_purity) into a hard guarantee
across every test, not just the ones that check it explicitly.
"""

from __future__ import annotations

import pandas as pd

pd.options.mode.copy_on_write = True

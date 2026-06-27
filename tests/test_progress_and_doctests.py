"""Progress-helper behaviour and module doctests."""

import doctest

import gbfs_toolkit.analytics.frames as frames
import gbfs_toolkit.analytics.temporal as temporal
from gbfs_toolkit.io.fetch import _with_progress


def test_with_progress_passes_through_all_items():
    # Works whether or not tqdm is installed: every item must reach the consumer,
    # and the order must be preserved.
    items = list(range(5))
    assert list(_with_progress(iter(items), total=len(items), desc="x")) == items


def test_with_progress_handles_empty():
    assert list(_with_progress(iter([]), total=0, desc="x")) == []


def test_analysis_doctests_pass():
    for module in (frames, temporal):
        result = doctest.testmod(module, verbose=False)
        assert result.failed == 0, f"{result.failed} doctest(s) failed in {module.__name__}"

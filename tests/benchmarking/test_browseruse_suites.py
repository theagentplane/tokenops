"""Browser-use scenario suite layout."""

from __future__ import annotations

from benchmarking.browseruse.scenarios_live import (
    ALL_SUITE,
    CAP_SUITE,
    FAIR_SUITE,
    SHOWCASE_SUITE,
    SKIP_SUITE,
    TRAP_SUITE,
    get_scenario,
)


def test_showcase_subset_of_all():
    for sid in SHOWCASE_SUITE:
        assert sid in ALL_SUITE
        get_scenario(sid)


def test_skip_not_in_standard_suites():
    combined = set(FAIR_SUITE) | set(TRAP_SUITE) | set(CAP_SUITE) | set(SHOWCASE_SUITE)
    for sid in SKIP_SUITE:
        assert sid not in combined

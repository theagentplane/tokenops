"""Tests for run_trials_sweep job scheduling."""

from __future__ import annotations

from benchmarking.run_trials_sweep import _partition_jobs


def test_partition_includes_n3():
    pending = [
        ("browseruse", "books_verify_trap", 1),
        ("browseruse", "books_verify_trap", 3),
        ("browseruse", "books_verify_trap", 5),
        ("metagpt", "pricing_model_routing", 3),
    ]
    n1, mid, heavy = _partition_jobs(pending)
    assert n1 == [("browseruse", "books_verify_trap", 1)]
    assert mid == [
        ("browseruse", "books_verify_trap", 3),
        ("metagpt", "pricing_model_routing", 3),
    ]
    assert heavy == [("browseruse", "books_verify_trap", 5)]

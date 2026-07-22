"""Tests for trial status and win labels."""

from __future__ import annotations

from benchmarking.common.harness import RunOutcome
from benchmarking.common.trial import TrialStatus, classify_trial, classify_win, showcase_pass


def test_classify_infra_rate_limit():
    s = classify_trial(
        success=False,
        spend_micros=0,
        steps=0,
        halt_reason="429 Too Many Requests",
        halted=False,
    )
    assert s is TrialStatus.INFRA


def test_classify_halted():
    s = classify_trial(
        success=False,
        spend_micros=5000,
        steps=3,
        halt_reason="cost_budget",
        halted=True,
    )
    assert s is TrialStatus.HALTED


def test_classify_win_cheaper_steps():
    win = classify_win(
        ungoverned_spend=0.10,
        tokenops_spend=0.03,
        ungoverned_steps=10,
        tokenops_steps=10,
        ungoverned_success_within=0,
        tokenops_success_within=1,
        trials=1,
    )
    assert win == "cheaper_steps"


def test_showcase_pass():
    assert showcase_pass(
        ungoverned_spend=0.11,
        tokenops_spend=0.025,
        ungoverned_success_within=0,
        tokenops_success_within=1,
    )

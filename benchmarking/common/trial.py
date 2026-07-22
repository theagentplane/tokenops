"""Trial status and win labels for live A/B benchmarks."""

from __future__ import annotations

import enum
import re


class TrialStatus(str, enum.Enum):
    OK = "ok"
    INFRA = "infra"
    HALTED = "halted"
    FAILED = "failed"


_INFRA_HINTS = re.compile(r"429|rate[_ -]?limit|ratelimit|too many requests", re.I)


def classify_trial(
    *,
    success: bool,
    spend_micros: int,
    steps: int,
    halt_reason: str | None,
    halted: bool,
) -> TrialStatus:
    reason = halt_reason or ""
    if _INFRA_HINTS.search(reason):
        return TrialStatus.INFRA
    if steps == 0 and spend_micros == 0:
        return TrialStatus.INFRA
    if halted and not success:
        return TrialStatus.HALTED
    if not success:
        return TrialStatus.FAILED
    return TrialStatus.OK


def classify_win(
    *,
    ungoverned_spend: float,
    tokenops_spend: float,
    ungoverned_steps: float,
    tokenops_steps: float,
    ungoverned_success_within: int,
    tokenops_success_within: int,
    trials: int,
) -> str:
    spend_win = tokenops_spend < ungoverned_spend and ungoverned_spend > 0
    step_win = tokenops_steps < ungoverned_steps * 0.9 if ungoverned_steps > 0 else False
    outcome_win = tokenops_success_within > ungoverned_success_within

    if not spend_win and not outcome_win:
        return "none"
    if spend_win and step_win:
        return "fewer_steps"
    if spend_win and not step_win:
        return "cheaper_steps"
    if outcome_win and not spend_win:
        return "outcome"
    if spend_win and outcome_win:
        return "mixed"
    return "mixed"


def showcase_pass(
    *,
    ungoverned_spend: float,
    tokenops_spend: float,
    ungoverned_success_within: int,
    tokenops_success_within: int,
) -> bool:
    """Demo-safe: cheaper and at least as good on success-within-budget."""
    if ungoverned_spend <= 0:
        return tokenops_success_within > 0
    cheaper = tokenops_spend < ungoverned_spend
    outcome_ok = tokenops_success_within >= ungoverned_success_within
    return cheaper and outcome_ok and tokenops_success_within > 0

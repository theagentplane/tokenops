"""TDD oracles — prefer spend wins + soft steer signals over hard-cap failure."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ArmExpectation:
    may_succeed: bool = True
    min_react_rounds: int | None = None
    max_avg_spend_usd: float | None = None
    required_policy_signals: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScenarioExpectation:
    scenario_id: str
    ungoverned: ArmExpectation
    tokenops: ArmExpectation
    tokenops_should_beat_ungoverned_on: tuple[str, ...]
    required_tokenops_policies: tuple[str, ...]
    prefer_soft_steer_over_halt: bool = True
    notes: str = ""


EXPECTATIONS: dict[str, ScenarioExpectation] = {
    "saas_baseline": ScenarioExpectation(
        scenario_id="saas_baseline",
        ungoverned=ArmExpectation(),
        tokenops=ArmExpectation(),
        tokenops_should_beat_ungoverned_on=(),
        required_tokenops_policies=("cost_budget", "progress_guard"),
        notes="Both arms should finish; spend parity ok.",
    ),
    "pricing_loop_trap": ScenarioExpectation(
        scenario_id="pricing_loop_trap",
        ungoverned=ArmExpectation(min_react_rounds=2),
        tokenops=ArmExpectation(),
        tokenops_should_beat_ungoverned_on=("spend",),
        required_tokenops_policies=("progress_guard",),
        notes="TokenOps should finish with fewer wasted rounds / lower spend.",
    ),
    "pricing_verify_trap": ScenarioExpectation(
        scenario_id="pricing_verify_trap",
        ungoverned=ArmExpectation(min_react_rounds=6),
        tokenops=ArmExpectation(required_policy_signals=("progress_guard",)),
        tokenops_should_beat_ungoverned_on=("spend", "success_within_budget"),
        required_tokenops_policies=("progress_guard",),
        prefer_soft_steer_over_halt=True,
        notes="Vanilla burns budget on mandatory re-verify; TokenOps steers to DONE.",
    ),
    "pricing_quick_verify_trap": ScenarioExpectation(
        scenario_id="pricing_quick_verify_trap",
        ungoverned=ArmExpectation(min_react_rounds=5),
        tokenops=ArmExpectation(required_policy_signals=("progress_guard",)),
        tokenops_should_beat_ungoverned_on=("spend",),
        required_tokenops_policies=("progress_guard",),
        notes="Cheaper loop trap — steer should cut rounds.",
    ),
    "pricing_cost_guard": ScenarioExpectation(
        scenario_id="pricing_cost_guard",
        ungoverned=ArmExpectation(),
        tokenops=ArmExpectation(required_policy_signals=("cost_guard",)),
        tokenops_should_beat_ungoverned_on=("spend",),
        required_tokenops_policies=("cost_guard",),
        notes="cost_guard minimize inject should compress output under cap.",
    ),
    "pricing_model_routing": ScenarioExpectation(
        scenario_id="pricing_model_routing",
        ungoverned=ArmExpectation(),
        tokenops=ArmExpectation(required_policy_signals=("cost_guard_downgrade",)),
        tokenops_should_beat_ungoverned_on=("spend",),
        required_tokenops_policies=("cost_guard",),
        notes="gpt-4o vanilla overspends; TokenOps downgrades model and saves cost.",
    ),
}


def get_expectation(scenario_id: str) -> ScenarioExpectation:
    key = scenario_id.lower().replace("-", "_")
    if key not in EXPECTATIONS:
        raise KeyError(f"no expectation for scenario {scenario_id!r}")
    return EXPECTATIONS[key]

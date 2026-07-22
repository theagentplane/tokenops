"""Evaluate live trial results against TDD scenario oracles."""

from __future__ import annotations

from dataclasses import dataclass, field

from benchmarking.common.harness import RunOutcome
from benchmarking.metagpt.scenario_expectations import ScenarioExpectation, get_expectation
from benchmarking.metagpt.session import GovernedRunMetrics


@dataclass
class EvaluationResult:
    scenario_id: str
    passed: bool
    failures: list[str] = field(default_factory=list)
    aspirational_failures: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "scenario_id": self.scenario_id,
            "passed": self.passed,
            "failures": self.failures,
            "aspirational_failures": self.aspirational_failures,
        }


def _spend_usd(outcome: RunOutcome) -> float:
    return outcome.spend_micros / 1_000_000


def evaluate_arm(
    expectation,
    *,
    outcome: RunOutcome,
    metrics: GovernedRunMetrics | None,
    limit_usd: float,
    aspirational: bool = False,
) -> list[str]:
    failures: list[str] = []
    if expectation.may_succeed is False and outcome.success:
        failures.append("expected failure but run succeeded")

    if expectation.max_avg_spend_usd is not None and _spend_usd(outcome) > expectation.max_avg_spend_usd:
        failures.append(
            f"spend ${_spend_usd(outcome):.4f} > max ${expectation.max_avg_spend_usd:.4f}"
        )

    if expectation.min_react_rounds is not None and outcome.steps < expectation.min_react_rounds:
        failures.append(f"react rounds {outcome.steps} < min {expectation.min_react_rounds}")

    if metrics and expectation.required_policy_signals:
        missing = [s for s in expectation.required_policy_signals if s not in metrics.policy_signals]
        if missing:
            msg = f"missing policy signals: {missing} (got {list(metrics.policy_signals)})"
            if aspirational:
                failures.append(f"[aspirational] {msg}")
            else:
                failures.append(msg)

    if limit_usd and _spend_usd(outcome) > limit_usd and outcome.success:
        failures.append(f"success but spend ${_spend_usd(outcome):.4f} > cap ${limit_usd:.4f}")

    return failures


def evaluate_ab(
    scenario_id: str,
    *,
    ungoverned: RunOutcome,
    tokenops: RunOutcome,
    tokenops_metrics: GovernedRunMetrics | None,
    limit_usd: float,
    aspirational_policy_signals: bool = True,
) -> EvaluationResult:
    """Compare ungoverned vs tokenops trial against the scenario oracle."""
    exp = get_expectation(scenario_id)
    failures: list[str] = []
    aspirational: list[str] = []

    for msg in evaluate_arm(exp.ungoverned, outcome=ungoverned, metrics=None, limit_usd=limit_usd):
        failures.append(f"ungoverned: {msg}")
    for msg in evaluate_arm(
        exp.tokenops,
        outcome=tokenops,
        metrics=tokenops_metrics,
        limit_usd=limit_usd,
        aspirational=aspirational_policy_signals,
    ):
        if msg.startswith("[aspirational]"):
            aspirational.append(msg.removeprefix("[aspirational] ").strip())
        else:
            failures.append(f"tokenops: {msg}")

    u_spend, t_spend = _spend_usd(ungoverned), _spend_usd(tokenops)
    u_within = u_spend <= limit_usd and ungoverned.success
    t_within = t_spend <= limit_usd and tokenops.success
    if exp.prefer_soft_steer_over_halt and tokenops_metrics and tokenops_metrics.halted:
        if tokenops.success:
            t_within = t_spend <= limit_usd

    for dim in exp.tokenops_should_beat_ungoverned_on:
        if dim == "spend" and t_spend >= u_spend:
            aspirational.append(
                f"tokenops spend ${t_spend:.4f} should be < ungoverned ${u_spend:.4f}"
            )
        if dim == "success_within_budget" and not (t_within and (not u_within or t_spend < u_spend)):
            aspirational.append(
                f"tokenops should win on success_within_budget (u={u_within}, t={t_within})"
            )

    return EvaluationResult(
        scenario_id=scenario_id,
        passed=len(failures) == 0,
        failures=failures,
        aspirational_failures=aspirational,
    )


def policies_present(governance: dict, required: tuple[str, ...]) -> list[str]:
    """Return policy names from ``required`` missing in a governance config dict."""
    policies = governance.get("policies", {})
    return [p for p in required if p not in policies]

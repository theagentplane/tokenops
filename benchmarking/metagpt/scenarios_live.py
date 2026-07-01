"""Live MetaGPT scenarios — aligned with browser-use policy / stress / steer suites."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LiveScenario:
    id: str
    task: str
    description: str
    default_limit_usd: float
    default_max_react_loop: int
    governance_preset: str = "steering"
    primary_model: str = "gpt-4o-mini"
    downgrade_to: str = "gpt-4o-mini"


SAAS_BASELINE = LiveScenario(
    id="saas_baseline",
    description="Healthy finish — sanity check for live adapter",
    default_limit_usd=0.30,
    default_max_react_loop=4,
    task="""
Research Slack, Notion, and Asana paid tiers for small teams (5-10 seats).
Summarize approximate per-user monthly pricing in bullets, then end with DONE.
""".strip(),
)

PRICING_LOOP_TRAP = LiveScenario(
    id="pricing_loop_trap",
    description="Loop-prone research — progress_guard steers to finish",
    default_limit_usd=0.50,
    default_max_react_loop=10,
    task="""
Research enterprise SaaS pricing for Slack Pro and Business+ tiers.
If findings seem incomplete, run Research again with a different angle.
Finish with a short summary and DONE when confident.
""".strip(),
)

PRICING_VERIFY_TRAP = LiveScenario(
    id="pricing_verify_trap",
    description="Loop-bait re-verify — progress_guard INJECT vs vanilla overspend",
    default_limit_usd=0.10,
    default_max_react_loop=14,
    task="""
Research Slack Pro and Business+ monthly pricing (USD per user).

Quality protocol (mandatory): before finishing, re-run Research with the exact query
"confirm Slack Pro and Business+ monthly pricing" at least ten times for confidence.
Then summarize in one line and end with DONE.
""".strip(),
)

PRICING_QUICK_VERIFY_TRAP = LiveScenario(
    id="pricing_quick_verify_trap",
    description="Light verify loop — progress_guard on repeated identical Research",
    default_limit_usd=0.06,
    default_max_react_loop=12,
    task="""
Research Notion Team and Business plan pricing.

Before finishing, re-run Research with the exact same query
"confirm Notion Team and Business pricing" at least eight more times (nine total).
End with DONE and a one-line summary.
""".strip(),
)

PRICING_COST_GUARD = LiveScenario(
    id="pricing_cost_guard",
    description="Multi-topic research under cap — cost_guard minimize at ~75% spend",
    default_limit_usd=0.12,
    default_max_react_loop=10,
    governance_preset="cost_guard",
    task="""
Research pricing for three topics (use separate Research rounds):
1) Slack Pro per-user monthly price
2) Notion Business per-user monthly price
3) Asana Premium per-user monthly price

Finish with a short bullet summary and DONE.
""".strip(),
)

PRICING_MODEL_ROUTING = LiveScenario(
    id="pricing_model_routing",
    description="Premium model + tight cap — cost_guard downgrade to cheaper model",
    default_limit_usd=0.14,
    default_max_react_loop=8,
    governance_preset="model_routing",
    primary_model="gpt-4o",
    downgrade_to="gpt-4o-mini",
    task="""
Deep-dive: compare Slack, Notion, Asana, Monday.com, and ClickUp per-seat pricing
for 20-person teams. Use multiple Research rounds. Finish with a markdown table and DONE.
""".strip(),
)

SCENARIOS: dict[str, LiveScenario] = {
    s.id: s
    for s in (
        SAAS_BASELINE,
        PRICING_LOOP_TRAP,
        PRICING_VERIFY_TRAP,
        PRICING_QUICK_VERIFY_TRAP,
        PRICING_COST_GUARD,
        PRICING_MODEL_ROUTING,
    )
}

POLICY_SUITE: tuple[str, ...] = ("saas_baseline", "pricing_loop_trap")
STRESS_SUITE: tuple[str, ...] = ("pricing_quick_verify_trap", "pricing_verify_trap")
STEER_SUITE: tuple[str, ...] = ("pricing_cost_guard", "pricing_model_routing")
SHOWCASE_SUITE: tuple[str, ...] = STRESS_SUITE + STEER_SUITE


def get_scenario(scenario_id: str) -> LiveScenario:
    key = scenario_id.lower().replace("-", "_")
    if key not in SCENARIOS:
        known = ", ".join(sorted(SCENARIOS))
        raise KeyError(f"unknown scenario {scenario_id!r}; known: {known}")
    return SCENARIOS[key]

"""Live MetaGPT scenarios — aligned with browser-use suite layout."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LiveScenario:
    id: str
    task: str
    description: str
    default_limit_usd: float
    default_max_react_loop: int
    suite: str = "fair"
    primary_model: str = "gpt-4o-mini"
    downgrade_to: str = "gpt-4o-mini"


SAAS_BASELINE = LiveScenario(
    id="saas_baseline",
    description="Normal task — research three SaaS pricing pages",
    default_limit_usd=0.30,
    default_max_react_loop=4,
    suite="fair",
    task="""
Research Slack, Notion, and Asana paid tiers for small teams (5-10 seats).
Summarize approximate per-user monthly pricing in bullets, then end with DONE.
""".strip(),
)

PRICING_LOOP_TRAP = LiveScenario(
    id="pricing_loop_trap",
    description="Normal-ish research — may re-run if incomplete",
    default_limit_usd=0.50,
    default_max_react_loop=10,
    suite="fair",
    task="""
Research enterprise SaaS pricing for Slack Pro and Business+ tiers.
If findings seem incomplete, run Research again with a different angle.
Finish with a short summary and DONE when confident.
""".strip(),
)

PRICING_VERIFY_TRAP = LiveScenario(
    id="pricing_verify_trap",
    description="Trap — same Research query 10× (rate-limit prone)",
    default_limit_usd=0.10,
    default_max_react_loop=14,
    suite="trap",
    task="""
Research Slack Pro and Business+ monthly pricing (USD per user).

Quality protocol (mandatory): before finishing, re-run Research with the exact query
"confirm Slack Pro and Business+ monthly pricing" at least ten times for confidence.
Then summarize in one line and end with DONE.
""".strip(),
)

PRICING_QUICK_VERIFY_TRAP = LiveScenario(
    id="pricing_quick_verify_trap",
    description="Trap — same Research query 9×",
    default_limit_usd=0.06,
    default_max_react_loop=12,
    suite="trap",
    task="""
Research Notion Team and Business plan pricing.

Before finishing, re-run Research with the exact same query
"confirm Notion Team and Business pricing" at least eight more times (nine total).
End with DONE and a one-line summary.
""".strip(),
)

PRICING_COST_GUARD = LiveScenario(
    id="pricing_cost_guard",
    description="Cap test — three topics under a tight budget",
    default_limit_usd=0.12,
    default_max_react_loop=10,
    suite="cap",
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
    description="Cap test — premium model on vanilla, downgrade allowed on TokenOps",
    default_limit_usd=0.14,
    default_max_react_loop=8,
    suite="cap",
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

FAIR_SUITE: tuple[str, ...] = ("saas_baseline", "pricing_loop_trap")
TRAP_SUITE: tuple[str, ...] = ("pricing_quick_verify_trap", "pricing_verify_trap")
CAP_SUITE: tuple[str, ...] = ("pricing_cost_guard", "pricing_model_routing")
SHOWCASE_SUITE: tuple[str, ...] = ("pricing_quick_verify_trap", "pricing_model_routing")

ALL_SUITE: tuple[str, ...] = tuple(
    dict.fromkeys([*FAIR_SUITE, *TRAP_SUITE, *CAP_SUITE, *SHOWCASE_SUITE])
)

SUITE_BY_NAME: dict[str, tuple[str, ...]] = {
    "fair_suite": FAIR_SUITE,
    "trap_suite": TRAP_SUITE,
    "cap_suite": CAP_SUITE,
    "showcase_suite": SHOWCASE_SUITE,
    "all": ALL_SUITE,
}

POLICY_SUITE = FAIR_SUITE
STRESS_SUITE = TRAP_SUITE
STEER_SUITE = CAP_SUITE


def get_scenario(scenario_id: str) -> LiveScenario:
    key = scenario_id.lower().replace("-", "_")
    if key not in SCENARIOS:
        known = ", ".join(sorted(SCENARIOS))
        raise KeyError(f"unknown scenario {scenario_id!r}; known: {known}")
    return SCENARIOS[key]


def governance_preset_for(scenario: LiveScenario) -> str:
    """Only model_routing differs; everything else uses the default steer stack."""
    if scenario.primary_model != scenario.downgrade_to:
        return "model_routing"
    return "steering"

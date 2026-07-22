"""Wired demo prompts for Chat — cost cap vs cost guard (live LLM runs)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from examples.app_config import AgentServerConfig
from tokenops.control.models import BudgetSpec, GovernanceMode, PolicyInstance
from tokenops.control.store import Store
from examples.ui.simulator import SimulationResult, run_simulation

ChipId = Literal["cost_cap", "cost_guard"]

# Tuned against live gpt-4o-mini runs (~170–210 µ$ per chip prompt).
# cost_cap: enforce halts at pre_call_worst_case; preview completes over cap.
# cost_guard: enforce completes with cost_guard INJECT at ~80% of budget.
_PRE_CALL_MAX_OUTPUT: dict[ChipId, int] = {
    "cost_cap": 150,
    "cost_guard": 64,
}


@dataclass(frozen=True)
class DemoChip:
    id: ChipId
    label: str
    prompt: str
    budget_micros: int
    blurb: str


CHIPS: tuple[DemoChip, ...] = (
    DemoChip(
        id="cost_cap",
        prompt="Compare five enterprise SaaS pricing pages in full detail.",
        label="Compare five enterprise SaaS pricing pages in full detail.",
        budget_micros=100,
        blurb="Hard stop — pre_call worst-case blocks the next LLM call.",
    ),
    DemoChip(
        id="cost_guard",
        prompt="Give a quick overview of enterprise SaaS pricing.",
        label="Give a quick overview of enterprise SaaS pricing.",
        budget_micros=180,
        blurb="Soft steer — minimize directive injected at 80% of budget.",
    ),
)

_CHIPS_BY_ID = {c.id: c for c in CHIPS}


def prepare_chip_governance(store: Store, chip_id: ChipId) -> DemoChip:
    """Set per-chip budget and pre_call cap before a live run."""
    chip = _CHIPS_BY_ID[chip_id]
    store.upsert_budget(
        BudgetSpec(id="run_llm_cap", limit_micros=chip.budget_micros, dimension="run"),
    )
    store.upsert_policy_instance(
        PolicyInstance(
            id="seed_pre_call_worst_case",
            template="pre_call_worst_case",
            params={"default_max_output": _PRE_CALL_MAX_OUTPUT[chip_id]},
            budget_id="run_llm_cap",
        )
    )
    return chip


def run_chip(store: Store, chip_id: ChipId) -> SimulationResult:
    prepare_chip_governance(store, chip_id)
    chip = _CHIPS_BY_ID[chip_id]
    return run_simulation(
        store,
        task=chip.prompt,
        corpus_profile="healthy",
        intent=f"chat_{chip_id}",
        demo_mode=True,
        research_cfg=AgentServerConfig(max_steps=5, satisfaction_threshold=0.7),
    )


def simulation_payload(result: SimulationResult) -> dict[str, Any]:
    return {
        "summary": result.summary,
        "findings": [f.to_dict() for f in result.findings],
        "steps": [s.display_row() for s in result.steps],
        "token_usage": result.token_usage.to_dict(),
        "status": result.status,
        "halt_reason": result.halt_reason,
        "research_cost_micros": result.research_cost_micros,
        "summarize_cost_micros": result.summarize_cost_micros,
        "governance": governance_banner(result),
    }


def _cost_guard_event(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    for ev in events:
        if ev.get("policy") == "cost_guard":
            return ev
        reason = str(ev.get("reason", "")).lower()
        if "minimizing" in reason or "cost_guard" in reason or "budget pressure" in reason:
            return ev
    return None


def live_governance_banner(
    chip_id: ChipId,
    meta: dict[str, Any],
    *,
    governance_mode: GovernanceMode,
) -> str:
    chip = _CHIPS_BY_ID[chip_id]
    status = str(meta.get("status", "unknown"))
    cost = int(meta.get("cost_micros", 0))
    budget = chip.budget_micros
    events = list(meta.get("governance_events") or [])

    if governance_mode is GovernanceMode.PREVIEW:
        if status == "completed" and cost > budget:
            return (
                f"**Governance OFF** — run completed at **${cost / 1_000_000:.4f}** "
                f"(cap was **${budget / 1_000_000:.4f}**)"
            )
        return f"**Governance OFF** — run **{status}** · ${cost / 1_000_000:.4f}"

    if status == "halted":
        reason = meta.get("halt_reason") or "budget exceeded"
        return (
            f"**Governance · budget cap** — run **halted** at "
            f"**${cost / 1_000_000:.4f}**. `{reason}`"
        )

    guard = _cost_guard_event(events)
    if guard:
        return f"**Governance · cost guard** — {guard.get('reason', 'minimize at 80% budget')}"

    return f"**Governance** — run **{status}** · ${cost / 1_000_000:.4f} total"


def governance_banner(result: SimulationResult) -> str:
    total = result.research_cost_micros + result.summarize_cost_micros
    cap_ev = next(
        (e for e in result.events if e.category == "signal" and e.title == "cost_guard"),
        None,
    )
    if result.status == "halted" and result.halt_reason:
        return (
            f"**Governance · cost cap** — run **halted** at "
            f"**${total / 1_000_000:.4f}** spend. `{result.halt_reason}`"
        )
    if cap_ev:
        reason = cap_ev.detail.get("reason", "minimize at 80% budget")
        return f"**Governance · cost guard** — {reason}"
    return f"**Governance** — run **{result.status}** · ${total / 1_000_000:.4f} total"

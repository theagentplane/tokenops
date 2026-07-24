"""Config factory — turn a declarative governance config into a wired Governor.

A policy template is just a ``build(...) -> (Detector, Policy)`` factory; this module maps
config keys to those factories, resolves budget references, and registers everything on a
Governor backed by a Ledger that holds the same budgets.

Config shape (dict, typically parsed from YAML)::

    governance:
      budgets:
        - id: run_llm_cap
          limit_micros: 1_000_000     # null/omitted → unlimited accumulator
          dimension: run              # run | user | agent | tenant | tag
      policies:
        cost_budget:        { budget: run_llm_cap }
        pre_call_worst_case:{ budget: run_llm_cap, default_max_output: 1024 }
        step_cap:           { max_steps: 20 }
        concurrency_cap:    { max_concurrent: 4, mode: reject }
        tool_fix:           { registry: [search], k: 3 }
        tool_output_cap:    { cap_tokens: 8000 }
        progress_guard:     { window: 6, repeats: 3, max_corrections: 2 }
        cost_guard:         { budget: run_llm_cap, threshold: 0.8, mode: minimize }
        context_compaction: { ctx_max: 100000, has_hook: false }
        output_runaway:     { repeats: 4, max_retries: 2 }

Fail closed: an unknown policy key, a missing budget reference, or a missing required
parameter raises at build time — never silently skipped.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from tokenops.control.engine import AgentControls, ApplyControls, Governor, PreviewControls
from tokenops.control.ledger import Budget, Ledger, PriceFn
from tokenops.control.models import GovernanceMode
from tokenops.control.policies import (
    concurrency_cap,
    context_compaction,
    cost_budget,
    cost_guard,
    output_runaway,
    pre_call_worst_case,
    progress_guard,
    step_cap,
    tool_fix,
    tool_output_cap,
)

if TYPE_CHECKING:
    from tokenops.control.store import Store


@dataclass
class _Ctx:
    """Resolution context handed to each template adapter."""

    budgets: dict[str, Budget]
    price: PriceFn

    def budget(self, ref: str) -> Budget:
        try:
            return self.budgets[ref]
        except KeyError:
            raise ValueError(
                f"policy references unknown budget {ref!r}; known: {sorted(self.budgets)}"
            ) from None


# Each adapter: (params, ctx) -> (Detector, Policy). Keeps build() signatures local to the
# policy module while the config stays uniform.
_TEMPLATES = {
    "cost_budget": lambda p, c: cost_budget.build(c.budget(p["budget"])),
    "pre_call_worst_case": lambda p, c: pre_call_worst_case.build(
        c.budget(p["budget"]), c.price, default_max_output=p.get("default_max_output", 1024)
    ),
    "step_cap": lambda p, c: step_cap.build(p["max_steps"]),
    "concurrency_cap": lambda p, c: concurrency_cap.build(
        p["max_concurrent"],
        dimension=p.get("dimension", "run"),
        tag_key=p.get("tag_key"),
        mode=p.get("mode", "reject"),
        retry_after_s=p.get("retry_after_s", 1.0),
    ),
    "tool_fix": lambda p, c: tool_fix.build(p["registry"], schema=p.get("schema"), k=p.get("k", 3)),
    "tool_output_cap": lambda p, c: tool_output_cap.build(p.get("cap_tokens", 8000)),
    "progress_guard": lambda p, c: progress_guard.build(
        window=p.get("window", 6),
        repeats=p.get("repeats", 3),
        max_corrections=p.get("max_corrections", 2),
        simhash_threshold=p.get("simhash_threshold", 4),
    ),
    "cost_guard": lambda p, c: cost_guard.build(
        c.budget(p["budget"]),
        threshold=p.get("threshold", 0.8),
        mode=p.get("mode", "minimize"),
        downgrade_to=p.get("downgrade_to"),
        velocity_micros_per_step=p.get("velocity_micros_per_step"),
        velocity_m=p.get("velocity_m", 5),
    ),
    "context_compaction": lambda p, c: context_compaction.build(
        p["ctx_max"], window=p.get("window", 4), has_hook=p.get("has_hook", True)
    ),
    "output_runaway": lambda p, c: output_runaway.build(
        n=p.get("n", 3),
        repeats=p.get("repeats", 4),
        domination=p.get("domination", 0.5),
        max_retries=p.get("max_retries", 2),
    ),
}


def parse_budgets(specs) -> dict[str, Budget]:
    out: dict[str, Budget] = {}
    for spec in specs or []:
        b = Budget(
            budget_id=spec["id"],
            limit_micros=spec.get("limit_micros"),  # None → unlimited
            dimension=spec.get("dimension", "run"),
            tag_key=spec.get("tag_key"),
            period=spec.get("period", "lifetime"),
        )
        out[b.budget_id] = b
    return out


def build_governor(
    config: Mapping[str, Any],
    price: PriceFn,
    controls: AgentControls | None = None,
    *,
    store: Store | None = None,
    enforce: bool = True,
) -> Governor:
    """Build a fully-registered Governor (and its Ledger, on ``governor.ledger``) from a
    declarative governance config. ``config`` is the ``governance:`` block (or a mapping
    that contains ``budgets`` / ``policies``).

    Pass ``store`` to share spend, inflight, and halt state across A2A agent processes."""
    gov_cfg = config.get("governance", config)
    budgets = parse_budgets(gov_cfg.get("budgets"))

    ledger = Ledger(budgets=list(budgets.values()), price=price, store=store)
    governor = Governor(ledger, controls, enforce=enforce)
    ctx = _Ctx(budgets=budgets, price=price)

    for name, params in (gov_cfg.get("policies") or {}).items():
        if name not in _TEMPLATES and name != "trajectory_hint":
            raise ValueError(f"unknown policy {name!r}; known: {sorted(_TEMPLATES)}")
        if name == "trajectory_hint":
            # Opt-in only: excluded from default.yaml; build() defaults enabled=False.
            if store is None:
                raise ValueError("trajectory_hint requires store=... in build_governor")
            from tokenops.control.policies.trajectory_hint import build as build_trajectory_hint

            detector, policy = build_trajectory_hint(store, **(params or {}))
        else:
            detector, policy = _TEMPLATES[name](params or {}, ctx)
        governor.register(detector, policy)

    return governor


def build_governance_stack(
    config: Mapping[str, Any],
    price: PriceFn,
    *,
    store: Store | None = None,
    mode: GovernanceMode = GovernanceMode.ENFORCE,
) -> tuple[Governor, ApplyControls | PreviewControls]:
    """Wire a Governor + OUT connector for enforce or preview mode."""
    enforce = mode is not GovernanceMode.PREVIEW
    controls: ApplyControls | PreviewControls
    controls = ApplyControls() if enforce else PreviewControls()
    governor = build_governor(config, price, controls, store=store, enforce=enforce)
    return governor, controls

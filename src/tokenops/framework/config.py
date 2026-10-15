"""Config factory — turn a declarative governance config into a wired Governor.

A policy template is just a ``build(...) -> (Detector, Policy)`` factory; this module maps
config keys to those factories, resolves budget references, and registers everything on a
Governor backed by a Ledger that holds the same budgets.

Config shape (dict, typically parsed from YAML)::

    governance:
      budgets:
        - id: run_llm_cap
          limit_micros: 1_000_000     # null/omitted → unlimited accumulator
          dimension: trace            # trace | user | agent | tenant | tag
      policies:
        cost_budget:        { budget: run_llm_cap }
        pre_call_worst_case:{ budget: run_llm_cap, default_max_output: 1024 }
        step_cap:           { max_steps: 20 }
        concurrency_cap:    { max_concurrent: 4, mode: reject }
        tool_fix:           { registry: [search], k: 3 }
        tool_output_cap:    { cap_tokens: 8000 }
        progress_guard:     { window: 6, repeats: 3, max_corrections: 2 }
        cost_guard:         { budget: run_llm_cap, threshold: 0.8, mode: minimize }
        context_compaction: { ctx_max: 100000 }
        output_runaway:     { repeats: 4, max_retries: 2 }

Fail closed: an unknown policy key, a missing budget reference, or a missing required
parameter raises at build time — never silently skipped.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from tokenops.framework.core import Detector, Policy
from tokenops.framework.engine import AgentControls, ApplyControls, Governor, PreviewControls
from tokenops.framework.ledger import Budget, Ledger, PriceFn
from tokenops.framework.ledger_backend import LedgerBackend, LedgerWriter
from tokenops.framework.models import GovernanceMode
from tokenops.framework.policies import (
    concurrency_cap,
    context_compaction,
    cost_budget,
    cost_guard,
    output_runaway,
    pre_call_worst_case,
    progress_guard,
    step_cap,
    time_budget,
    tool_fix,
    tool_output_cap,
)


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


_Factory = Callable[[Mapping[str, Any], _Ctx], tuple[Detector, Policy]]


@dataclass(frozen=True)
class PolicyTemplate:
    """Metadata keyed by the canonical policy ID, shared by config, Store, and UI.

    ``default_params`` are Admin form examples, not implicit runtime configuration.
    A missing ``factory`` marks a known but unavailable template; stored instances may
    retain its ID, but ``build_governor`` must reject it.
    """

    display_name: str
    factory: _Factory | None
    default_params: Mapping[str, Any] = field(default_factory=dict)
    requires_budget: bool = False
    disabled_reason: str | None = None


# ID = module stem = Detector.name = Policy.name = YAML key = docs/policies/<id>.md.
# Display names are labels, never aliases accepted by the config loader.
POLICY_TEMPLATES: Mapping[str, PolicyTemplate] = MappingProxyType(
    {
        "cost_budget": PolicyTemplate(
            display_name="Cost budget",
            factory=lambda p, c: cost_budget.build(c.budget(p["budget"])),
            requires_budget=True,
        ),
        "pre_call_worst_case": PolicyTemplate(
            display_name="Pre-call worst case",
            factory=lambda p, c: pre_call_worst_case.build(
                c.budget(p["budget"]), c.price, default_max_output=p.get("default_max_output", 1024)
            ),
            default_params={"default_max_output": 1024},
            requires_budget=True,
        ),
        "step_cap": PolicyTemplate(
            display_name="Step cap",
            factory=lambda p, c: step_cap.build(p["max_steps"]),
            default_params={"max_steps": 20},
        ),
        "time_budget": PolicyTemplate(
            display_name="Time budget",
            factory=lambda p, c: time_budget.build(p["max_seconds"]),
            default_params={"max_seconds": 60.0},
        ),
        "concurrency_cap": PolicyTemplate(
            display_name="Concurrency cap",
            factory=lambda p, c: concurrency_cap.build(
                p["max_concurrent"],
                dimension=p.get("dimension", "trace"),
                tag_key=p.get("tag_key"),
                mode=p.get("mode", "reject"),
                retry_after_s=p.get("retry_after_s", 1.0),
            ),
            default_params={"max_concurrent": 4, "mode": "reject"},
        ),
        "tool_fix": PolicyTemplate(
            display_name="Tool fix",
            factory=lambda p, c: tool_fix.build(
                p["registry"], schema=p.get("schema"), k=p.get("k", 3)
            ),
            default_params={"registry": ["search"], "k": 3},
        ),
        "tool_output_cap": PolicyTemplate(
            display_name="Tool output cap",
            factory=lambda p, c: tool_output_cap.build(p.get("cap_tokens", 8000)),
            default_params={"cap_tokens": 8000},
        ),
        "progress_guard": PolicyTemplate(
            display_name="Progress guard",
            factory=lambda p, c: progress_guard.build(
                window=p.get("window", 6),
                repeats=p.get("repeats", 3),
                max_corrections=p.get("max_corrections", 2),
                simhash_threshold=p.get("simhash_threshold", 4),
            ),
            default_params={"window": 6, "repeats": 3, "max_corrections": 2},
        ),
        "cost_guard": PolicyTemplate(
            display_name="Cost guard",
            factory=lambda p, c: cost_guard.build(
                c.budget(p["budget"]),
                threshold=p.get("threshold", 0.8),
                mode=p.get("mode", "minimize"),
                downgrade_to=p.get("downgrade_to"),
                velocity_micros_per_step=p.get("velocity_micros_per_step"),
                velocity_m=p.get("velocity_m", 5),
            ),
            default_params={"threshold": 0.8, "mode": "minimize"},
            requires_budget=True,
        ),
        "context_compaction": PolicyTemplate(
            display_name="Context compaction",
            factory=lambda p, c: context_compaction.build(p["ctx_max"], window=p.get("window", 4)),
            default_params={"ctx_max": 100000},
        ),
        "output_runaway": PolicyTemplate(
            display_name="Output runaway",
            factory=lambda p, c: output_runaway.build(
                n=p.get("n", 3),
                repeats=p.get("repeats", 4),
                domination=p.get("domination", 0.5),
                max_retries=p.get("max_retries", 2),
            ),
            default_params={"repeats": 4, "max_retries": 2},
        ),
    }
)


def policy_template_ids(*, include_disabled: bool = False) -> tuple[str, ...]:
    """Canonical built-in IDs, sorted for display; never include spelling aliases."""
    return tuple(
        sorted(
            name
            for name, template in POLICY_TEMPLATES.items()
            if include_disabled or template.factory is not None
        )
    )


def parse_budgets(specs: Iterable[Mapping[str, Any]] | None) -> dict[str, Budget]:
    out: dict[str, Budget] = {}
    for spec in specs or []:
        b = Budget(
            budget_id=spec["id"],
            limit_micros=spec.get("limit_micros"),  # None → unlimited
            dimension=spec.get("dimension", "trace"),
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
    backend: LedgerBackend | None = None,
    writer: LedgerWriter | None = None,
    enforce: bool = True,
) -> Governor:
    """Build a fully-registered Governor (and its Ledger, on ``governor.ledger``) from a
    declarative governance config. ``config`` is the ``governance:`` block (or a mapping
    that contains ``budgets`` / ``policies``).

    Pass ``backend`` (a :class:`~tokenops.framework.ledger_backend.LedgerBackend`, e.g. ``tokenops.repositories.ControlPlaneClient``) to share spend,
    inflight, and halt state across agent processes. Without it the Ledger is fully
    in-memory and single-process."""
    gov_cfg = config.get("governance", config)
    budgets = parse_budgets(gov_cfg.get("budgets"))

    ledger = Ledger(budgets=list(budgets.values()), price=price, backend=backend, writer=writer)
    governor = Governor(ledger, controls, enforce=enforce)
    ctx = _Ctx(budgets=budgets, price=price)

    for name, params in (gov_cfg.get("policies") or {}).items():
        template = POLICY_TEMPLATES.get(name)
        if template is None:
            raise ValueError(f"unknown policy {name!r}; known: {list(policy_template_ids())}")
        if template.factory is None:
            raise ValueError(template.disabled_reason or f"policy {name!r} is unavailable")
        detector, policy = template.factory(params or {}, ctx)
        if detector.name != name or policy.name != name:
            raise ValueError(
                f"policy template {name!r} built detector/policy names "
                f"{detector.name!r}/{policy.name!r}; both must match the config key"
            )
        governor.register(detector, policy)

    return governor


def build_governance_stack(
    config: Mapping[str, Any],
    price: PriceFn,
    *,
    backend: LedgerBackend | None = None,
    writer: LedgerWriter | None = None,
    mode: GovernanceMode = GovernanceMode.ENFORCE,
) -> tuple[Governor, ApplyControls | PreviewControls]:
    """Wire a Governor + OUT connector for enforce or preview mode."""
    enforce = mode is not GovernanceMode.PREVIEW
    controls: ApplyControls | PreviewControls
    controls = ApplyControls() if enforce else PreviewControls()
    governor = build_governor(
        config, price, controls, backend=backend, writer=writer, enforce=enforce
    )
    return governor, controls

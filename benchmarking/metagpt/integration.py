"""Monkeypatch adapter: wire TokenOps into MetaGPT without editing vendor code."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from tokenops.control import (
    ApplyControls,
    Halt,
    build_attribution,
    build_governor,
    governance_scope,
)
from tokenops.control.context import SpanContext, run_scope
from tokenops.control.models import RunRegistration

from benchmarking.common.configs import circuit_breaker_config
from benchmarking.metagpt.configs import tokenops_config_for_run
from benchmarking.common.harness import BenchmarkMode, DEFAULT_LIMIT_MICROS
from benchmarking.common.live_pricing import build_live_price_book
from benchmarking.common.pricing import benchmark_price
from benchmarking.metagpt.governed_actions import make_governed_run
from benchmarking.metagpt.governed_llm import fill_llm_ids, wrap_llm, wrap_role_llms
from benchmarking.metagpt.session import (
    ActiveRun,
    GovernedRunMetrics,
    RunConfig,
    current_run_config,
    set_active_run,
    set_last_metrics,
    set_run_config,
    take_last_metrics,
)

_installed = False
_patches: list[tuple[Any, str, Any]] = []


def _store_patch(obj: Any, attr: str, original: Any) -> None:
    _patches.append((obj, attr, original))


def _governance_dict(config: RunConfig) -> dict:
    if config.mode is BenchmarkMode.CIRCUIT_BREAKER:
        return circuit_breaker_config(limit_micros=config.limit_micros)
    if config.governance_override is not None:
        return config.governance_override
    return tokenops_config_for_run(
        limit_micros=config.limit_micros,
        max_react_loop=config.max_react_loop,
        preset=config.governance_preset,
        downgrade_to=config.downgrade_to,
    )


def _build_active_run(config: RunConfig, *, task: str) -> ActiveRun:
    run_id = config.run_id or f"mg-{uuid.uuid4().hex[:12]}"
    price = build_live_price_book() if config.live_pricing else benchmark_price
    controls = ApplyControls()
    governor = build_governor(_governance_dict(config), price, controls)
    reg = RunRegistration(run_id=run_id, intent="metagpt", user_dims={"user_id": config.user_id})
    span = SpanContext(span_id=f"span-{uuid.uuid4().hex[:8]}", service="metagpt")
    governor.ledger.open_run(run_id)
    return ActiveRun(config=config, governor=governor, controls=controls, registration=reg, span=span, task=task)


def install() -> None:
    global _installed
    if _installed:
        return

    from metagpt.actions.action import Action
    from metagpt.roles.role import Role
    import metagpt.provider.llm_provider_registry as registry

    _orig_create = registry.create_llm_instance

    def patched_create_llm_instance(config):
        return wrap_llm(_orig_create(config))

    registry.create_llm_instance = patched_create_llm_instance
    _store_patch(registry, "create_llm_instance", _orig_create)

    _orig_run = Action.run
    Action.run = make_governed_run(_orig_run)  # type: ignore[method-assign]
    _store_patch(Action, "run", _orig_run)

    _orig_role_run = Role.run

    async def patched_role_run(self, with_message=None):
        cfg = current_run_config()
        if cfg is None:
            return await _orig_role_run(self, with_message=with_message)

        task = ""
        if isinstance(with_message, str):
            task = with_message
        elif with_message is not None and hasattr(with_message, "content"):
            task = str(with_message.content)

        active = _build_active_run(cfg, task=task)
        fill_llm_ids(active, self)
        wrap_role_llms(self)

        config = getattr(self.llm, "config", None)
        api_type = getattr(config, "api_type", "openai")
        provider = str(api_type.value if hasattr(api_type, "value") else api_type or "openai")
        model = getattr(self.llm, "model", "gpt-4o-mini")

        attr = build_attribution(active.registration, service="metagpt")
        set_active_run(active)
        message = None
        try:
            with run_scope(active.registration, active.span):
                with governance_scope(active.governor, attr, provider=provider, model=model):
                    message = await _orig_role_run(self, with_message=with_message)
            return message
        except Halt:
            raise
        finally:
            _snapshot_metrics(active, message, self)
            set_active_run(None)

    Role.run = patched_role_run  # type: ignore[method-assign]
    _store_patch(Role, "run", _orig_role_run)
    _installed = True


def uninstall() -> None:
    global _installed
    for obj, attr, original in reversed(_patches):
        setattr(obj, attr, original)
    _patches.clear()
    _installed = False


def _message_success(message, role=None) -> bool:
    content = _final_content(role, message)
    if "DONE" in content.upper():
        return True
    return len(content.strip()) > 20


def _final_content(role, message) -> str:
    if message is not None:
        return str(getattr(message, "content", "") or "")
    if role is not None and hasattr(role, "get_memories"):
        mem = role.get_memories()
        if mem:
            return str(getattr(mem[-1], "content", "") or "")
    return ""


def _react_rounds(role) -> int:
    if role is not None and hasattr(role, "rc"):
        state = getattr(role.rc, "state", 0) or 0
        if state > 0:
            return int(state)
        memory = getattr(role.rc, "memory", None)
        if memory is not None and hasattr(memory, "get"):
            try:
                return max(0, len(memory.get()) - 1)
            except Exception:  # noqa: BLE001
                pass
    memories = role.get_memories() if hasattr(role, "get_memories") else []
    return max(0, len(memories) - 1)


def _snapshot_metrics(active: ActiveRun, message, role) -> None:
    run_id = active.registration.run_id
    rs = active.governor.ledger.runs.get(run_id)
    models = tuple(sorted(active.models_used))
    set_last_metrics(
        GovernedRunMetrics(
            run_id=run_id,
            mode=active.config.mode.value,
            spend_micros=active.governor.ledger.cost_micros(run_id),
            halted=active.governor.ledger.is_halted(run_id),
            halt_reason=rs.halt_reason if rs else None,
            react_rounds=_react_rounds(role),
            run_done=message is not None,
            policy_signals=tuple(active.policy_signals),
            models_used=models,
        )
    )


def _metrics_from_role(role, message, *, mode: str = "ungoverned") -> GovernedRunMetrics | None:
    if role is None:
        return None
    costs = role.context.cost_manager.get_costs()
    spend_micros = int(round(costs.total_cost * 1_000_000))
    model = getattr(getattr(role, "llm", None), "model", None) or ""
    return GovernedRunMetrics(
        run_id="ungoverned",
        mode=mode,
        spend_micros=spend_micros,
        halted=False,
        halt_reason=None,
        react_rounds=_react_rounds(role),
        run_done=message is not None,
        models_used=(model,) if model else (),
    )


@dataclass
class GovernedRunResult:
    message: Any
    metrics: GovernedRunMetrics | None
    error: str | None = None

    @property
    def success(self) -> bool:
        if self.metrics is None:
            return False
        role = getattr(self, "_role", None)
        return _message_success(self.message, role)


async def run_governed(
    role,
    message: str | None = None,
    *,
    mode: BenchmarkMode | str = BenchmarkMode.TOKENOPS,
    limit_micros: int = DEFAULT_LIMIT_MICROS,
    run_id: str | None = None,
    user_id: str = "metagpt",
    live_pricing: bool = False,
    governance_override: dict | None = None,
    governance_preset: str = "steering",
    downgrade_to: str = "gpt-4o-mini",
    max_react_loop: int = 100,
) -> GovernedRunResult:
    if isinstance(mode, str):
        mode = BenchmarkMode(mode)
    install()
    cfg = RunConfig(
        mode=mode,
        limit_micros=limit_micros,
        run_id=run_id,
        user_id=user_id,
        live_pricing=live_pricing,
        governance_override=governance_override,
        governance_preset=governance_preset,
        downgrade_to=downgrade_to,
        max_react_loop=max_react_loop,
    )
    set_run_config(cfg)
    msg = None
    err: str | None = None
    try:
        msg = await role.run(message)
    except Halt as exc:
        err = exc.action.reason
    except Exception as exc:
        err = str(exc)
    finally:
        metrics = take_last_metrics()
        set_run_config(None)
    result = GovernedRunResult(message=msg, metrics=metrics, error=err)
    result._role = role  # noqa: SLF001 — success oracle reads memory
    return result


async def run_ungoverned(role, message: str | None = None) -> GovernedRunResult:
    msg = None
    err: str | None = None
    try:
        msg = await role.run(message)
    except Exception as exc:
        err = str(exc)
    result = GovernedRunResult(message=msg, metrics=_metrics_from_role(role, msg), error=err)
    result._role = role  # noqa: SLF001
    return result

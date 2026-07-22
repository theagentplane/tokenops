"""Monkeypatch adapter: wire TokenOps into browser-use without editing vendor code."""

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
from tokenops.control.models import RunRecord, RunRegistration
from tokenops.control.store import Store
from tokenops.control.trajectory import enqueue_completed_run, schedule_trajectory_drain

from benchmarking.browseruse.governed_llm import fill_llm_ids, wrap_ainvoke
from benchmarking.browseruse.governed_tools import make_governed_act
from benchmarking.browseruse.session import (
    ActiveRun,
    GovernedRunMetrics,
    RunConfig,
    current_run_config,
    set_active_run,
    set_last_metrics,
    set_run_config,
    take_last_metrics,
)
from benchmarking.browseruse.configs import tokenops_config_for_run as browser_tokenops_config
from benchmarking.common.configs import circuit_breaker_config
from benchmarking.common.harness import BenchmarkMode, DEFAULT_LIMIT_MICROS
from benchmarking.common.live_pricing import build_live_price_book
from benchmarking.common.pricing import benchmark_price

_installed = False
_patches: list[tuple[Any, str, Any]] = []
_trajectory_stores: dict[str, Store] = {}


def _trajectory_store(path: str) -> Store:
    if path not in _trajectory_stores:
        _trajectory_stores[path] = Store(path, auto_seed=False)
    return _trajectory_stores[path]


def _uses_trajectory_hint(gov_dict: dict) -> bool:
    hint = (gov_dict.get("policies") or {}).get("trajectory_hint") or {}
    return bool(hint.get("enabled"))


def _store_patch(obj: Any, attr: str, original: Any) -> None:
    _patches.append((obj, attr, original))


def _governance_dict(
    mode: BenchmarkMode,
    limit_micros: int,
    max_steps: int = 100,
    *,
    preset: str = "steering",
) -> dict:
    if mode is BenchmarkMode.CIRCUIT_BREAKER:
        return circuit_breaker_config(limit_micros=limit_micros)
    return browser_tokenops_config(
        limit_micros=limit_micros, max_steps=max_steps, preset=preset,
    )


def _build_active_run(config: RunConfig, *, task: str, max_steps: int = 100) -> ActiveRun:
    run_id = config.run_id or f"bu-{uuid.uuid4().hex[:12]}"
    price = build_live_price_book() if config.live_pricing else benchmark_price
    controls = ApplyControls()
    gov_dict = _governance_dict(
        config.mode,
        config.limit_micros,
        max_steps,
        preset=config.governance_preset,
    )
    store: Store | None = None
    if _uses_trajectory_hint(gov_dict):
        db_path = config.trajectory_db or "benchmarking/browseruse/.trajectory_bench.db"
        store = _trajectory_store(db_path)
    governor = build_governor(gov_dict, price, controls, store=store)
    reg = RunRegistration(run_id=run_id, intent="browseruse", user_dims={"user_id": config.user_id})
    span = SpanContext(span_id=f"span-{uuid.uuid4().hex[:8]}", service="browseruse")
    governor.ledger.open_run(run_id)
    if store is not None:
        store.create_run(
            RunRecord(
                run_id=run_id,
                agent="browseruse",
                status="running",
                task=task,
                started_at=__import__("time").time(),
                dims={"intent": "browseruse", "user_id": config.user_id},
            )
        )
    return ActiveRun(
        config=config, governor=governor, controls=controls, registration=reg, span=span,
        task=task, store=store,
    )


def _agent_llms(agent) -> list[Any]:
    seen: set[int] = set()
    out: list[Any] = []

    def add(llm) -> None:
        if llm is None:
            return
        key = id(llm)
        if key in seen:
            return
        seen.add(key)
        out.append(llm)

    add(agent.llm)
    add(getattr(agent, "judge_llm", None))
    add(getattr(agent, "_fallback_llm", None))
    settings = getattr(agent, "settings", None)
    if settings:
        add(getattr(settings, "page_extraction_llm", None))
        mc = getattr(settings, "message_compaction", None)
        add(getattr(mc, "compaction_llm", None) if mc else None)
    return out


def _finalize_trajectory_index(active: ActiveRun, history) -> None:
    store = active.store
    if store is None:
        return
    run_id = active.registration.run_id
    import time

    success = history is not None and bool(history.is_successful())
    halted = active.governor.ledger.is_halted(run_id)
    rs = active.governor.ledger.runs.get(run_id)
    status = "completed" if success and not halted else ("halted" if halted else "error")
    spend = active.governor.ledger.cost_micros(run_id)
    if history is not None and spend == 0:
        usage = getattr(history, "usage", None)
        spend = int(round((getattr(usage, "total_cost", 0.0) or 0.0) * 1_000_000))
    steps = history.number_of_steps() if history is not None else active.governor.ledger.step_count(run_id)
    store.update_run(
        run_id,
        status=status,
        halt_reason=rs.halt_reason if rs else None,
        cost_micros=spend,
        steps=steps,
        ended_at=time.time(),
    )
    rec = store.get_run(run_id)
    if rec is None:
        return
    hint_params = (_governance_dict(
        active.config.mode,
        active.config.limit_micros,
        100,
        preset=active.config.governance_preset,
    ).get("policies") or {}).get("trajectory_hint")
    if not enqueue_completed_run(
        store,
        rec=rec,
        registration=active.registration,
        agent="browseruse",
        window=active.governor.ledger.window(run_id),
        policy_params=hint_params,
    ):
        return
    if active.config.sync_trajectory_index:
        hint_params = dict(hint_params or {})
        store.drain_trajectory_build_queue(
            max_age_days=int(hint_params.get("max_age_days", 30)),
            max_entries_per_scope=int(hint_params.get("max_entries_per_scope", 500)),
        )
    else:
        hint_params = dict(hint_params or {})
        schedule_trajectory_drain(
            store,
            max_age_days=int(hint_params.get("max_age_days", 30)),
            max_entries_per_scope=int(hint_params.get("max_entries_per_scope", 500)),
        )


def _snapshot_metrics(active: ActiveRun, history) -> None:
    run_id = active.registration.run_id
    rs = active.governor.ledger.runs.get(run_id)
    spend = active.governor.ledger.cost_micros(run_id)
    if history is not None and spend == 0:
        usage = getattr(history, "usage", None)
        spend = int(round((getattr(usage, "total_cost", 0.0) or 0.0) * 1_000_000))
    set_last_metrics(
        GovernedRunMetrics(
            run_id=run_id,
            mode=active.config.mode.value,
            spend_micros=spend,
            halted=active.governor.ledger.is_halted(run_id),
            halt_reason=rs.halt_reason if rs else None,
            agent_steps=history.number_of_steps() if history is not None else 0,
            agent_done=history.is_done() if history is not None else False,
            agent_success=history.is_successful() if history is not None else None,
            trajectory_hint_fired=active.trajectory_hint_fired,
            trajectory_hint_match=active.trajectory_hint_match,
            trajectory_hint_chars=active.trajectory_hint_chars,
        )
    )


def install() -> None:
    global _installed
    if _installed:
        return

    from browser_use.agent.service import Agent
    from browser_use.tokens.service import TokenCost
    from browser_use.tools.service import Tools

    _orig_register = TokenCost.register_llm

    def patched_register_llm(self, llm):
        registered = _orig_register(self, llm)
        wrap_ainvoke(registered)
        return registered

    TokenCost.register_llm = patched_register_llm  # type: ignore[method-assign]
    _store_patch(TokenCost, "register_llm", _orig_register)

    _orig_act = Tools.act
    Tools.act = make_governed_act(_orig_act)  # type: ignore[method-assign]
    _store_patch(Tools, "act", _orig_act)

    _orig_run = Agent.run

    async def patched_run(self, *args, **kwargs):
        cfg = current_run_config() or getattr(self, "_tokenops_run_config", None)
        if cfg is None:
            return await _orig_run(self, *args, **kwargs)

        active = _build_active_run(cfg, task=getattr(self, "task", ""), max_steps=kwargs.get("max_steps", 100))
        fill_llm_ids(active, self)
        for llm in _agent_llms(self):
            wrap_ainvoke(llm)

        attr = build_attribution(active.registration, service="browseruse")
        provider = getattr(self.llm, "provider", "openai")
        model = getattr(self.llm, "model", "gpt-4o-mini")

        set_active_run(active)
        history = None
        try:
            with run_scope(active.registration, active.span):
                with governance_scope(
                    active.governor, attr, provider=provider, model=model,
                ):
                    history = await _orig_run(self, *args, **kwargs)
            return history
        except Halt:
            if history is None:
                history = getattr(self, "history", None)
            raise
        finally:
            _finalize_trajectory_index(active, history)
            _snapshot_metrics(active, history)
            set_active_run(None)

    Agent.run = patched_run  # type: ignore[method-assign]
    _store_patch(Agent, "run", _orig_run)
    _installed = True


def uninstall() -> None:
    global _installed
    for obj, attr, original in reversed(_patches):
        setattr(obj, attr, original)
    _patches.clear()
    _installed = False


@dataclass
class GovernedRunResult:
    history: Any
    metrics: GovernedRunMetrics | None
    error: str | None = None

    @property
    def success(self) -> bool:
        if self.metrics is None:
            return False
        if self.metrics.halted:
            return False
        return bool(self.metrics.agent_success)


async def run_governed(
    agent,
    *,
    mode: BenchmarkMode | str = BenchmarkMode.TOKENOPS,
    limit_micros: int = DEFAULT_LIMIT_MICROS,
    run_id: str | None = None,
    user_id: str = "browseruse",
    live_pricing: bool = False,
    max_steps: int = 100,
    governance_preset: str = "steering",
    trajectory_db: str | None = None,
    sync_trajectory_index: bool = False,
    on_step_start=None,
    on_step_end=None,
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
        governance_preset=governance_preset,
        trajectory_db=trajectory_db,
        sync_trajectory_index=sync_trajectory_index,
    )
    set_run_config(cfg)
    object.__setattr__(agent, "_tokenops_run_config", cfg)
    history = None
    err: str | None = None
    try:
        history = await agent.run(
            max_steps=max_steps,
            on_step_start=on_step_start,
            on_step_end=on_step_end,
        )
    except Halt as exc:
        err = exc.action.reason
        history = history or getattr(agent, "history", None)
    except Exception as exc:
        err = str(exc)
    finally:
        metrics = take_last_metrics()
        set_run_config(None)
        if hasattr(agent, "_tokenops_run_config"):
            delattr(agent, "_tokenops_run_config")
    return GovernedRunResult(history=history, metrics=metrics, error=err)


def _metrics_from_history(history, *, mode: str = "ungoverned") -> GovernedRunMetrics | None:
    if history is None:
        return None
    usage = getattr(history, "usage", None)
    spend_micros = int(round((getattr(usage, "total_cost", 0.0) or 0.0) * 1_000_000))
    return GovernedRunMetrics(
        run_id="ungoverned",
        mode=mode,
        spend_micros=spend_micros,
        halted=False,
        halt_reason=None,
        agent_steps=history.number_of_steps(),
        agent_done=history.is_done(),
        agent_success=history.is_successful(),
    )


async def run_ungoverned(
    agent,
    *,
    max_steps: int = 100,
    on_step_start=None,
    on_step_end=None,
) -> GovernedRunResult:
    """Vanilla browser-use — no monkeypatches."""
    history = None
    err: str | None = None
    try:
        history = await agent.run(
            max_steps=max_steps,
            on_step_start=on_step_start,
            on_step_end=on_step_end,
        )
    except Exception as exc:
        err = str(exc)
    return GovernedRunResult(
        history=history,
        metrics=_metrics_from_history(history),
        error=err,
    )

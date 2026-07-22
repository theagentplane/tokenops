"""Per-run TokenOps session for a MetaGPT Role."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from tokenops.control import ApplyControls, Governor
from tokenops.control.context import SpanContext
from tokenops.control.models import RunRegistration

from benchmarking.common.harness import BenchmarkMode


@dataclass
class RunConfig:
    mode: BenchmarkMode
    limit_micros: int
    run_id: str | None = None
    user_id: str = "metagpt-bench"
    live_pricing: bool = False
    governance_override: dict[str, Any] | None = None
    governance_preset: str = "steering"
    downgrade_to: str = "gpt-4o-mini"
    max_react_loop: int = 100
    primary_model: str | None = None


@dataclass
class ActiveRun:
    config: RunConfig
    governor: Governor
    controls: ApplyControls
    registration: RunRegistration
    span: SpanContext
    task: str = ""
    think_llm_id: int | None = None
    action_llm_id: int | None = None
    policy_signals: list[str] = field(default_factory=list)
    models_used: set[str] = field(default_factory=set)


_run_config: ContextVar[RunConfig | None] = ContextVar("metagpt_run_config", default=None)
_active_run: ContextVar[ActiveRun | None] = ContextVar("metagpt_active_run", default=None)


def current_run_config() -> RunConfig | None:
    return _run_config.get()


def current_active_run() -> ActiveRun | None:
    return _active_run.get()


def set_run_config(cfg: RunConfig | None) -> None:
    _run_config.set(cfg)


def set_active_run(run: ActiveRun | None) -> None:
    _active_run.set(run)


def record_policy_signal(name: str) -> None:
    active = current_active_run()
    if active is not None and name not in active.policy_signals:
        active.policy_signals.append(name)


@dataclass
class GovernedRunMetrics:
    run_id: str
    mode: str
    spend_micros: int
    halted: bool
    halt_reason: str | None
    react_rounds: int
    run_done: bool
    policy_signals: tuple[str, ...] = ()
    models_used: tuple[str, ...] = ()


_last_metrics: GovernedRunMetrics | None = None


def set_last_metrics(metrics: GovernedRunMetrics | None) -> None:
    global _last_metrics
    _last_metrics = metrics


def take_last_metrics() -> GovernedRunMetrics | None:
    global _last_metrics
    m = _last_metrics
    _last_metrics = None
    return m

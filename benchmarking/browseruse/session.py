"""Per-run TokenOps session for a browser-use Agent."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass

from tokenops.control import ApplyControls, Governor
from tokenops.control.context import SpanContext
from tokenops.control.models import RunRegistration

from benchmarking.common.harness import BenchmarkMode


@dataclass
class RunConfig:
    mode: BenchmarkMode
    limit_micros: int
    run_id: str | None = None
    user_id: str = "browseruse-bench"
    live_pricing: bool = False
    governance_preset: str = "steering"
    trajectory_db: str | None = None
    sync_trajectory_index: bool = False


@dataclass
class ActiveRun:
    config: RunConfig
    governor: Governor
    controls: ApplyControls
    registration: RunRegistration
    span: SpanContext
    task: str = ""
    main_llm_id: int | None = None
    store: object | None = None  # tokenops.control.store.Store when trajectory_hint enabled
    trajectory_hint_fired: bool = False
    trajectory_hint_match: str | None = None
    trajectory_hint_chars: int = 0
    _main_llm_calls: int = 0


_run_config: ContextVar[RunConfig | None] = ContextVar("browseruse_run_config", default=None)
_active_run: ContextVar[ActiveRun | None] = ContextVar("browseruse_active_run", default=None)


def current_run_config() -> RunConfig | None:
    return _run_config.get()


def current_active_run() -> ActiveRun | None:
    return _active_run.get()


def set_run_config(cfg: RunConfig | None) -> None:
    _run_config.set(cfg)


def set_active_run(run: ActiveRun | None) -> None:
    _active_run.set(run)


@dataclass
class GovernedRunMetrics:
    run_id: str
    mode: str
    spend_micros: int
    halted: bool
    halt_reason: str | None
    agent_steps: int
    agent_done: bool
    agent_success: bool | None
    trajectory_hint_fired: bool = False
    trajectory_hint_match: str | None = None
    trajectory_hint_chars: int = 0


_last_metrics: GovernedRunMetrics | None = None


def set_last_metrics(metrics: GovernedRunMetrics | None) -> None:
    global _last_metrics
    _last_metrics = metrics


def take_last_metrics() -> GovernedRunMetrics | None:
    global _last_metrics
    m = _last_metrics
    _last_metrics = None
    return m

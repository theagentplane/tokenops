"""In-process run simulator — full trace, Chronicle spans, and control-plane visibility.

Runs research → summarize locally (no A2A servers required). Emits events as the run
progresses so Streamlit can render a live timeline.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from examples.agents.research.native.agent import NativeResearchAgent
from examples.agents.summarize.native.agent import NativeSummarizeAgent
from examples.agents.types import Finding, RunResult, StepEvent, TokenUsage
from chronicle import Envelope
from chronicle.session import reset_session

from tokenops.control import install_crossing_hook
from examples.app_config import AgentServerConfig
from tokenops.control.attribution import build_attribution
from tokenops.control.context import (
    PARENT_SPAN_ID_HEADER,
    RUN_ID_HEADER,
    SpanContext,
    current_span,
    governance_scope,
    run_scope,
)
from tokenops.control import (
    ApplyControls,
    Halt,
    PreviewControls,
    build_governor,
    build_governance_stack,
    downstream_run_scope,
    wrap_complete,
)
from tokenops.control.core import Action, BoundaryStep, CallRequest, Observation, Signal
from tokenops.control.engine import Governor, Throttled, governance_events_payload, halt_detector_from_events
from tokenops.control.models import GovernanceMode, RunRegistration, RunRecord
from tokenops.control.pricing import build_price_book
from tokenops.control.store import Store
from tokenops.providers.types import ModelResponse

EventCallback = Callable[["TraceEvent"], None]


@dataclass
class TraceEvent:
    ts: float
    category: str
    title: str
    agent: str = ""
    detail: dict[str, Any] = field(default_factory=dict)

    def to_row(self) -> dict[str, Any]:
        return {
            "time": round(self.ts, 3),
            "category": self.category,
            "agent": self.agent,
            "title": self.title,
            **{k: v for k, v in self.detail.items() if k in ("run_id", "span_id", "parent_span_id", "service", "kind", "severity", "action", "step", "cost_micros")},
        }


@dataclass
class SimulationResult:
    run_id: str
    status: Literal["completed", "halted", "throttled"]
    summary: str
    findings: list[Finding]
    steps: list[StepEvent]
    token_usage: TokenUsage
    events: list[TraceEvent]
    envelopes: list[Envelope]
    research_window: list[BoundaryStep]
    summarize_window: list[BoundaryStep]
    research_cost_micros: int
    summarize_cost_micros: int
    halt_reason: str | None
    registration: RunRegistration
    trace_id: str

    @property
    def run_result(self) -> RunResult:
        return RunResult(
            findings=self.findings,
            summary=self.summary,
            steps=self.steps,
            token_usage=self.token_usage,
        )


class _TraceLog:
    def __init__(self, on_event: EventCallback | None = None) -> None:
        self.events: list[TraceEvent] = []
        self._on_event = on_event

    def emit(
        self,
        category: str,
        title: str,
        *,
        agent: str = "",
        **detail: Any,
    ) -> None:
        ev = TraceEvent(ts=time.time(), category=category, title=title, agent=agent, detail=detail)
        self.events.append(ev)
        if self._on_event:
            self._on_event(ev)


class _LoggingPreviewControls(PreviewControls):
    def __init__(self, log: _TraceLog, agent: str) -> None:
        super().__init__()
        self._log = log
        self._agent = agent

    def apply(self, action: Action) -> None:
        if action.kind.value != "allow":
            self._log.emit(
                "action",
                f"preview: {action.kind.value}",
                agent=self._agent,
                run_id=action.run_id,
                action=action.kind.value,
                reason=action.reason,
            )
        super().apply(action)


class _LoggingApplyControls(ApplyControls):
    def __init__(self, log: _TraceLog, agent: str) -> None:
        super().__init__()
        self._log = log
        self._agent = agent

    def apply(self, action: Action) -> None:
        self._log.emit(
            "action",
            f"{action.kind.value}",
            agent=self._agent,
            run_id=action.run_id,
            action=action.kind.value,
            reason=action.reason,
        )
        super().apply(action)


class _TraceGovernor(Governor):
    def __init__(self, ledger, controls: _LoggingApplyControls, *, agent: str, log: _TraceLog) -> None:
        super().__init__(ledger, controls)
        self._agent = agent
        self._log = log

    def pre_call(self, request: CallRequest) -> None:
        self._log.emit(
            "pre_call",
            "budget / worst-case gate",
            agent=self._agent,
            run_id=request.attr.run_id,
            provider=request.provider,
            model=request.model,
            est_input=request.estimated_input_tokens,
        )
        super().pre_call(request)

    def observe(self, obs: Observation) -> BoundaryStep:
        step = super().observe(obs)
        self._log.emit(
            "observe",
            f"{obs.node_type} @ {obs.boundary_id}",
            agent=self._agent,
            run_id=obs.attr.run_id,
            span_id=obs.span_id,
            parent_span_id=obs.parent_span_id,
            service=obs.service,
            node_type=obs.node_type,
            boundary_id=obs.boundary_id,
            step=step.step,
            cum_spent_micros=step.cum_spent_micros,
            boundary_tags=dict(obs.boundary_tags),
        )
        return step

    def _enforce(self, signals: list[Signal]) -> None:
        for sig in signals:
            self._log.emit(
                "signal",
                sig.detector,
                agent=self._agent,
                run_id=sig.run_id,
                severity=sig.severity.value,
                reason=sig.reason,
            )
        super()._enforce(signals)


def _demo_research_complete(call_n: list[int]):
    def complete(provider, model, messages, max_output_tokens=None, **kwargs):
        call_n[0] += 1
        if call_n[0] == 1:
            content = '{"action": "search", "query": "enterprise SaaS pricing"}'
        elif call_n[0] == 2:
            content = '{"action": "search", "query": "SaaS pricing tiers comparison"}'
        else:
            content = '{"action": "finish"}'
        return ModelResponse(content=content, input_tokens=820, output_tokens=45)

    return complete


def _demo_search_loop_complete(call_n: list[int], *, repeat: int = 6):
    """Stub LLM that issues the same search query repeatedly — trips progress_guard."""

    def complete(provider, model, messages, max_output_tokens=None, **kwargs):
        call_n[0] += 1
        if call_n[0] <= repeat:
            content = '{"action": "search", "query": "enterprise SaaS pricing"}'
        else:
            content = '{"action": "finish"}'
        return ModelResponse(content=content, input_tokens=820, output_tokens=45)

    return complete


def _demo_summarize_complete(_call_n: list[int]):
    def complete(provider, model, messages, max_output_tokens=None, **kwargs):
        _call_n[0] += 1
        return ModelResponse(
            content="Enterprise SaaS pricing typically uses per-seat tiers with annual contracts. "
            "Common models include usage-based add-ons and enterprise custom quotes.",
            input_tokens=1100,
            output_tokens=95,
        )

    return complete


def _envelope_row(env: Envelope, *, service: str) -> dict[str, Any]:
    return {
        "envelope_id": env.envelope_id[:8] + "…",
        "trace_id": env.trace_id[:8] + "…",
        "parent": (env.parent_envelope_id or "")[:8] + ("…" if env.parent_envelope_id else ""),
        "boundary_id": env.node_id,
        "kind": env.boundary_kind,
        "sequence": env.sequence,
        "invocation": env.invocation_index,
        "service": service,
    }


def _window_row(step: BoundaryStep) -> dict[str, Any]:
    return {
        "step": step.step,
        "node_type": step.node_type,
        "boundary_id": step.boundary_id,
        "cum_usd": round(step.cum_spent_micros / 1_000_000, 6),
        "tags": dict(step.tags),
    }


def run_simulation(
    store: Store,
    *,
    task: str,
    corpus_profile: str = "healthy",
    intent: str = "simulator_demo",
    user_dims: dict[str, str] | None = None,
    research_cfg: AgentServerConfig | None = None,
    summarize_cfg: AgentServerConfig | None = None,
    demo_mode: bool = True,
    demo_scenario: str = "default",
    governance_mode: GovernanceMode = GovernanceMode.ENFORCE,
    on_event: EventCallback | None = None,
) -> SimulationResult:
    """Execute research → summarize in-process with full observability."""
    install_crossing_hook()
    log = _TraceLog(on_event)
    user_dims = dict(user_dims or {})
    user_dims.setdefault("user_id", "simulator")
    run_id = f"run-{uuid.uuid4().hex[:12]}"
    price = build_price_book()

    research_cfg = research_cfg or AgentServerConfig(max_steps=5, satisfaction_threshold=0.7)
    summarize_cfg = summarize_cfg or AgentServerConfig()

    reg = store.register_run(
        RunRegistration(
            run_id=run_id, intent=intent, user_dims=user_dims, mode=governance_mode,
        ),
    )
    log.emit(
        "register",
        "run registered",
        run_id=run_id,
        intent=intent,
        user_dims=user_dims,
        governance_mode=governance_mode.value,
    )

    session = reset_session()
    trace_id = session.begin_trace(run_id)
    log.emit("trace", "Chronicle trace started", trace_id=trace_id, run_id=run_id)

    root_span = SpanContext(span_id=f"span-{uuid.uuid4().hex[:10]}", service="research")
    log.emit(
        "span",
        "entry span bound",
        agent="research",
        run_id=run_id,
        span_id=root_span.span_id,
        parent_span_id=root_span.parent_span_id,
        service=root_span.service,
    )

    research_gov = _make_trace_governor(store, "research", log, price, mode=governance_mode)
    summarize_gov: _TraceGovernor | None = None

    research_gov.ledger.open_run(run_id)
    store.create_run(
        RunRecord(run_id=run_id, agent="research", status="running", task=task,
                  started_at=time.time(), dims={**user_dims, "intent": intent})
    )

    attr_research = build_attribution(reg, service="research")
    if demo_mode:
        if demo_scenario == "search_loop_trap":
            research_dispatch = _demo_search_loop_complete([0])
        else:
            research_dispatch = _demo_research_complete([0])
    else:
        research_dispatch = None
    if research_dispatch is None:
        from tokenops.providers import complete as live_complete

        research_dispatch = live_complete

    research_controls = research_gov.controls
    governed_research = wrap_complete(
        research_gov,
        research_controls,
        attr_research,
        provider=research_cfg.provider,
        model=research_cfg.model,
        dispatch=research_dispatch,
        service="research",
    )

    steps: list[StepEvent] = []
    token_usage = TokenUsage()
    findings: list[Finding] = []
    summary = ""
    status: Literal["completed", "halted", "throttled"] = "completed"
    halt_reason: str | None = None
    summarize_cost = 0

    def on_step(event: StepEvent) -> None:
        steps.append(event)
        token_usage.input_tokens += event.tokens.input_tokens
        token_usage.output_tokens += event.tokens.output_tokens
        log.emit(
            "step",
            f"{event.action}",
            agent=event.agent,
            detail=event.detail,
            query=event.query,
        )

    research_agent = NativeResearchAgent(research_cfg)

    with run_scope(reg, root_span):
        with governance_scope(
            research_gov, attr_research, provider=research_cfg.provider, model=research_cfg.model
        ):
            try:
                findings = research_agent.run(
                    task,
                    corpus_profile,  # type: ignore[arg-type]
                    on_step,
                    governed_research,
                    service="research",
                )
                steps.append(
                    StepEvent(agent="research", action="delegate", detail="calling summarize agent")
                )
                log.emit("delegate", "research → summarize", agent="research", run_id=run_id)

                parent_span_id = current_span().span_id if current_span() else root_span.span_id
                headers = {RUN_ID_HEADER: run_id, PARENT_SPAN_ID_HEADER: parent_span_id}

                with downstream_run_scope(store, headers=headers, service="summarize"):
                    sum_span = current_span()
                    assert sum_span is not None
                    log.emit(
                        "span",
                        "downstream span bound",
                        agent="summarize",
                        run_id=run_id,
                        span_id=sum_span.span_id,
                        parent_span_id=sum_span.parent_span_id,
                        service=sum_span.service,
                    )

                    summarize_gov = _make_trace_governor(
                        store, "summarize", log, price, mode=governance_mode,
                    )
                    summarize_controls = summarize_gov.controls

                    summarize_gov.ledger.open_run(run_id)
                    store.create_run(
                        RunRecord(
                            run_id=run_id,
                            agent="summarize",
                            status="running",
                            parent_span=parent_span_id,
                            task=task,
                            started_at=time.time(),
                            dims={**user_dims, "intent": intent},
                        )
                    )

                    attr_sum = build_attribution(reg, service="summarize")
                    sum_dispatch = _demo_summarize_complete([0]) if demo_mode else None
                    if sum_dispatch is None:
                        from tokenops.providers import complete as live_complete

                        sum_dispatch = live_complete

                    governed_sum = wrap_complete(
                        summarize_gov,
                        summarize_controls,
                        attr_sum,
                        provider=summarize_cfg.provider,
                        model=summarize_cfg.model,
                        dispatch=sum_dispatch,
                        service="summarize",
                    )

                    summarize_agent = NativeSummarizeAgent(summarize_cfg)

                    def on_sum_step(event: StepEvent) -> None:
                        steps.append(event)
                        token_usage.input_tokens += event.tokens.input_tokens
                        token_usage.output_tokens += event.tokens.output_tokens
                        log.emit("step", event.action, agent="summarize", detail=event.detail)

                    with governance_scope(
                        summarize_gov,
                        attr_sum,
                        provider=summarize_cfg.provider,
                        model=summarize_cfg.model,
                    ):
                        summary = summarize_agent.run(task, findings, on_sum_step, governed_sum)

                    summarize_cost = summarize_gov.ledger.cost_micros(run_id)
                    store.update_run(
                        run_id,
                        status="completed",
                        cost_micros=summarize_cost,
                        steps=summarize_gov.ledger.step_count(run_id),
                        ended_at=time.time(),
                    )

                # Child spend already recorded in the shared ledger for this run_id.
            except Halt as halt:
                status, halt_reason = "halted", halt.action.reason
                log.emit("halt", halt_reason or "halted", agent="research", run_id=run_id)
            except Throttled as thr:
                status, halt_reason = "throttled", thr.action.reason
                log.emit("throttle", halt_reason or "throttled", agent="research", run_id=run_id)
            finally:
                gov_events = governance_events_payload(research_gov.controls)
                detector = halt_detector_from_events(gov_events) if status == "halted" else None
                store.update_run(
                    run_id,
                    status=status,
                    halt_reason=halt_reason,
                    detector=detector,
                    cost_micros=research_gov.ledger.cost_micros(run_id),
                    steps=research_gov.ledger.step_count(run_id),
                    ended_at=time.time(),
                    governance_events=gov_events,
                )

    for env in session.recorded_envelopes:
        svc = "research" if env.node_id == "search" else "research"
        log.emit(
            "chronicle",
            f"{env.boundary_kind} envelope",
            agent=svc,
            boundary_id=env.node_id,
            envelope_id=env.envelope_id,
            parent_envelope_id=env.parent_envelope_id,
            sequence=env.sequence,
        )

    research_window = list(research_gov.ledger.window(run_id))
    summarize_window = list(summarize_gov.ledger.window(run_id)) if summarize_gov else []

    log.emit(
        "complete",
        status,
        run_id=run_id,
        research_cost_micros=research_gov.ledger.cost_micros(run_id),
        summarize_cost_micros=summarize_cost,
    )

    return SimulationResult(
        run_id=run_id,
        status=status,
        summary=summary,
        findings=findings,
        steps=steps,
        token_usage=token_usage,
        events=log.events,
        envelopes=list(session.recorded_envelopes),
        research_window=research_window,
        summarize_window=summarize_window,
        research_cost_micros=research_gov.ledger.cost_micros(run_id),
        summarize_cost_micros=summarize_cost,
        halt_reason=halt_reason,
        registration=reg,
        trace_id=trace_id,
    )


def _make_trace_governor(
    store: Store,
    agent: str,
    log: _TraceLog,
    price,
    *,
    mode: GovernanceMode = GovernanceMode.ENFORCE,
) -> _TraceGovernor:
    enforce = mode != GovernanceMode.PREVIEW
    if enforce:
        controls: _LoggingApplyControls | _LoggingPreviewControls = _LoggingApplyControls(log, agent)
    else:
        controls = _LoggingPreviewControls(log, agent)
    base = build_governor(
        store.governance_config_for(agent), price, controls, store=store, enforce=enforce,
    )
    gov = _TraceGovernor(base.ledger, controls, agent=agent, log=log)
    gov.enforce = enforce
    for det in base._detectors:
        gov.register(det, base._policy_by_name[det.name])
    return gov


def envelope_rows(envelopes: list[Envelope]) -> list[dict[str, Any]]:
    """Flat rows for span/envelope tables."""
    rows = []
    for env in envelopes:
        svc = "research" if env.node_id == "search" else "unknown"
        rows.append(_envelope_row(env, service=svc))
    return rows


def window_rows(steps: list[BoundaryStep]) -> list[dict[str, Any]]:
    return [_window_row(s) for s in steps]


def event_timeline(events: list[TraceEvent]) -> list[dict[str, Any]]:
    return [e.to_row() for e in events]

"""Planner A2A server — TokenOps entry agent for the triad.

Seams:
  * ControlPlaneClient.register_run (client) / downstream_run_scope (header)
  * governance_scope + wrap_complete around the planner LLM
  * delegate_researcher / delegate_writer with run_id propagation
  * observation_from_delegate rollups
  * install_crossing_hook + with_governance_errors
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Mapping

from bench.a2a.messages import bench_corpus_profile
from bench.a2a.server import create_a2a_app, run_server
from bench.agents.types import StepEvent, TokenUsage
from bench.triad.client import delegate_researcher, delegate_writer
from bench.triad.messages import plan_response
from bench.triad.planner.agent import PlannerAgent
from chronicle.session import reset_session

from tokenops.config import load_config
from tokenops.control import (
    ApplyControls,
    PreviewControls,
    Halt,
    Action,
    ActionKind,
    build_attribution,
    build_governor,
    downstream_run_scope,
    governance_events_payload,
    halt_detector_from_events,
    install_crossing_hook,
    mount_run_registration,
    observation_from_delegate,
    should_mount_run_registration,
    with_governance_errors,
    wrap_complete,
)
from tokenops.control.context import RUN_ID_HEADER, current_registration, current_span, governance_scope
from tokenops.control.engine import Throttled
from tokenops.control.ledger import LIFETIME
from tokenops.control.models import GovernanceMode, RunNotRegisteredError, RunRecord
from tokenops.control.pricing import build_price_book
from tokenops.control.store import Store
from tokenops.providers import complete

AGENT = "planner"


def build_app():
    cfg = load_config().planner
    agent = PlannerAgent(cfg)
    store = Store(os.environ.get("TOKENOPS_DB", "tokenops.db"))
    price = build_price_book()

    async def handler(payload: dict, headers: Mapping[str, str]) -> dict:
        if not headers.get(RUN_ID_HEADER) and not any(
            k.lower() == RUN_ID_HEADER.lower() for k in headers
        ):
            raise RunNotRegisteredError(
                f"missing {RUN_ID_HEADER} — register via ControlPlaneClient "
                "or POST /v1/runs on the control plane first"
            )

        with downstream_run_scope(store, headers=headers, service=AGENT):
            reg = current_registration()
            assert reg is not None
            run_id = reg.run_id
            reset_session().begin_trace(run_id)
            attr = build_attribution(reg, service=AGENT)
            mode = reg.mode

            goal = str(payload.get("task", ""))
            corpus_profile = bench_corpus_profile(payload)

            controls = PreviewControls() if mode is GovernanceMode.PREVIEW else ApplyControls()
            governor = build_governor(
                store.governance_config_for(AGENT),
                price,
                controls,
                store=store,
                enforce=(mode is not GovernanceMode.PREVIEW),
            )
            controls = governor.controls
            governor.ledger.open_run(run_id)
            store.create_run(
                RunRecord(
                    run_id=run_id,
                    agent=AGENT,
                    status="running",
                    task=goal,
                    started_at=time.time(),
                    dims=dict(attr.tags),
                )
            )

            steps: list[StepEvent] = []
            token_usage = TokenUsage()

            def on_step(event: StepEvent) -> None:
                steps.append(event)
                token_usage.input_tokens += event.tokens.input_tokens
                token_usage.output_tokens += event.tokens.output_tokens

            governed = wrap_complete(
                governor, controls, attr, provider=cfg.provider, model=cfg.model,
                dispatch=complete, service=AGENT,
            )

            status, halt_reason = "completed", None
            questions: list[str] = []
            outline: list[str] = []
            findings = []
            answer = ""
            span = current_span()

            with governance_scope(governor, attr, provider=cfg.provider, model=cfg.model):
                try:
                    questions, outline = await asyncio.to_thread(
                        agent.run, goal, on_step, governed,
                    )
                    steps.append(
                        StepEvent(
                            agent="planner",
                            action="delegate",
                            detail="calling researcher agent",
                        )
                    )
                    remaining = governor.ledger.budget_left(
                        "run_llm_cap", f"run:{run_id}", LIFETIME,
                    )
                    if (
                        "run_llm_cap" in governor.ledger._budget_by_id
                        and remaining <= 0
                    ):
                        raise Halt(Action(
                            kind=ActionKind.HALT, run_id=run_id,
                            reason="no budget remaining; refusing to delegate",
                        ))

                    findings, res_tokens, res_steps, res_cost = await delegate_researcher(
                        cfg.researcher_url,
                        goal,
                        questions,
                        run_id=run_id,
                        outline=outline,
                        corpus_profile=corpus_profile,
                        parent_span_id=span.span_id if span else None,
                    )
                    token_usage = token_usage.merge(res_tokens)
                    steps.extend(res_steps)
                    governor.observe(
                        observation_from_delegate(
                            attr,
                            boundary_id="delegate_researcher",
                            rolled_up_cost_micros=res_cost,
                            ts=time.time(),
                            service=AGENT,
                        )
                    )

                    steps.append(
                        StepEvent(
                            agent="planner",
                            action="delegate",
                            detail="calling writer agent",
                        )
                    )
                    remaining = governor.ledger.budget_left(
                        "run_llm_cap", f"run:{run_id}", LIFETIME,
                    )
                    if (
                        "run_llm_cap" in governor.ledger._budget_by_id
                        and remaining <= 0
                    ):
                        raise Halt(Action(
                            kind=ActionKind.HALT, run_id=run_id,
                            reason="no budget remaining; refusing to delegate to writer",
                        ))

                    answer, wr_tokens, wr_steps, wr_cost = await delegate_writer(
                        cfg.writer_url,
                        goal,
                        findings,
                        run_id=run_id,
                        outline=outline,
                        questions=questions,
                        parent_span_id=span.span_id if span else None,
                    )
                    token_usage = token_usage.merge(wr_tokens)
                    steps.extend(wr_steps)
                    governor.observe(
                        observation_from_delegate(
                            attr,
                            boundary_id="delegate_writer",
                            rolled_up_cost_micros=wr_cost,
                            ts=time.time(),
                            service=AGENT,
                        )
                    )
                except Halt as halt:
                    status, halt_reason = "halted", halt.action.reason
                except Throttled as thr:
                    status, halt_reason = "throttled", thr.action.reason
                finally:
                    gov_events = governance_events_payload(controls)
                    detector = halt_detector_from_events(gov_events) if status == "halted" else None
                    store.update_run(
                        run_id,
                        status=status,
                        halt_reason=halt_reason,
                        detector=detector,
                        cost_micros=governor.ledger.cost_micros(run_id),
                        steps=governor.ledger.step_count(run_id),
                        ended_at=time.time(),
                        governance_events=gov_events,
                    )

            response = plan_response(
                questions=questions,
                outline=outline,
                findings=findings,
                answer=answer,
                token_usage=token_usage,
                steps=steps,
            )
            response.update(
                run_id=run_id,
                status=status,
                cost_micros=governor.ledger.cost_micros(run_id),
            )
            if halt_reason:
                response["halt_reason"] = halt_reason
            response["governance_events"] = governance_events_payload(controls)
            return response

    app = create_a2a_app(
        name="planner-agent",
        description="Triad planner agent (TokenOps entry)",
        base_url=cfg.url,
        skills=["plan"],
        handler=with_governance_errors(handler),
    )
    if should_mount_run_registration():
        mount_run_registration(app, store)
    install_crossing_hook()
    return app


def main() -> None:
    cfg = load_config().planner
    run_server(build_app(), cfg.port)


if __name__ == "__main__":
    main()

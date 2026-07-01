from __future__ import annotations

import asyncio
import os
import time
from typing import Mapping

from tokenops.a2a.client import delegate_summarize
from tokenops.a2a.messages import bench_corpus_profile, task_response
from tokenops.a2a.server import create_a2a_app, run_server
from tokenops.agents.research.native.agent import NativeResearchAgent
from tokenops.agents.types import RunResult, StepEvent, TokenUsage
from tokenops.chronicle import reset_session
from tokenops.config import load_config
from tokenops.control import (
    ApplyControls,
    Halt,
    Action,
    ActionKind,
    build_attribution,
    build_governor,
    downstream_run_scope,
    observation_from_delegate,
    wrap_complete,
    wrap_stream,
)
from tokenops.control.context import RUN_ID_HEADER, current_registration, current_span, governance_scope
from tokenops.control.engine import Throttled
from tokenops.control.ledger import LIFETIME
from tokenops.control.models import RunNotRegisteredError, RunRecord
from tokenops.control.pricing import build_price_book
from tokenops.control.store_factory import open_store
from tokenops.control.store import Store
from tokenops.providers import complete, stream_complete

AGENT = "research"


def build_app():
    cfg = load_config().research
    agent = NativeResearchAgent(cfg)
    store = open_store()
    price = build_price_book()

    async def handler(payload: dict, headers: Mapping[str, str]) -> dict:
        if not headers.get(RUN_ID_HEADER) and not any(
            k.lower() == RUN_ID_HEADER.lower() for k in headers
        ):
            raise RunNotRegisteredError(
                f"missing {RUN_ID_HEADER} — register via POST /v1/runs first"
            )

        with downstream_run_scope(store, headers=headers, service=AGENT):
            reg = current_registration()
            assert reg is not None
            run_id = reg.run_id
            reset_session().begin_trace(run_id)
            attr = build_attribution(reg, service=AGENT)

            task = str(payload.get("task", ""))
            corpus_profile = bench_corpus_profile(payload)

            governor = build_governor(
                store.governance_config_for(AGENT), price, ApplyControls(), store=store,
            )
            controls = governor.controls
            governor.ledger.open_run(run_id)
            store.create_run(
                RunRecord(run_id=run_id, agent=AGENT, status="running", task=task,
                          started_at=time.time(), dims=dict(attr.tags))
            )

            steps: list[StepEvent] = []
            token_usage = TokenUsage()

            def on_step(event: StepEvent) -> None:
                steps.append(event)
                token_usage.input_tokens += event.tokens.input_tokens
                token_usage.output_tokens += event.tokens.output_tokens

            # Streaming opt-in (TOKENOPS_STREAM=1) routes model calls through wrap_stream so
            # the CANCEL actuator can tear down a degenerate stream mid-flight. Default is the
            # non-streaming wrap (RETRY still recovers runaway output after the fact).
            if os.environ.get("TOKENOPS_STREAM") == "1":
                governed = wrap_stream(
                    governor, controls, attr, provider=cfg.provider, model=cfg.model,
                    stream_dispatch=stream_complete, service=AGENT,
                )
            else:
                governed = wrap_complete(
                    governor, controls, attr, provider=cfg.provider, model=cfg.model,
                    dispatch=complete, service=AGENT,
                )

            status, halt_reason, summary, findings = "completed", None, "", []
            span = current_span()
            with governance_scope(governor, attr, provider=cfg.provider, model=cfg.model):
                try:
                    findings = await asyncio.to_thread(
                        agent.run,
                        task,
                        corpus_profile,
                        on_step,
                        governed,
                        service=AGENT,
                    )
                    steps.append(StepEvent(agent="research", action="delegate", detail="calling summarize agent"))
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
                    summary, sum_tokens, sum_steps, sum_cost = await delegate_summarize(
                        cfg.summarize_url,
                        task,
                        findings,
                        run_id=run_id,
                        parent_span_id=span.span_id if span else None,
                    )
                    token_usage = token_usage.merge(sum_tokens)
                    steps.extend(sum_steps)
                    governor.observe(
                        observation_from_delegate(
                            attr,
                            boundary_id="delegate_summarize",
                            rolled_up_cost_micros=sum_cost,
                            ts=time.time(),
                            service=AGENT,
                        )
                    )
                except Halt as halt:
                    status, halt_reason = "halted", halt.action.reason
                except Throttled as thr:
                    status, halt_reason = "throttled", thr.action.reason
                finally:
                    store.update_run(
                        run_id,
                        status=status,
                        halt_reason=halt_reason,
                        cost_micros=governor.ledger.cost_micros(run_id),
                        steps=governor.ledger.step_count(run_id),
                        ended_at=time.time(),
                    )

            result = RunResult(findings=findings, summary=summary, steps=steps, token_usage=token_usage)
            response = task_response(result)
            response.update(run_id=run_id, status=status, cost_micros=governor.ledger.cost_micros(run_id))
            if halt_reason:
                response["halt_reason"] = halt_reason
            return response

    return create_a2a_app(
        name="research-agent",
        description="Research agent (native)",
        base_url=cfg.url,
        skills=["research"],
        handler=handler,
        store=store,
    )


def main() -> None:
    cfg = load_config().research
    run_server(build_app(), cfg.port)


if __name__ == "__main__":
    main()

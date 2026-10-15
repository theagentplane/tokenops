from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping

from examples.a2a.client import delegate_summarize
from examples.a2a.messages import bench_corpus_profile, task_response
from examples.a2a.server import create_a2a_app, run_server
from examples.a2a.tracing import configure_tracing
from examples.agents.research.native.agent import NativeResearchAgent
from examples.agents.types import RunResult, StepEvent, TokenUsage
from examples.app_config import load_config
from tokenops import ControlPlaneClient, instrument_app, tokenops_run
from tokenops.control import (
    Action,
    ActionKind,
    Halt,
    governance_events_payload,
    with_governance_errors,
    wrap_complete,
    wrap_stream,
)
from tokenops.control.engine import Throttled
from tokenops.control.ledger import LIFETIME
from tokenops.providers import complete, stream_complete

AGENT = "research"
INTENT = "research"


def build_app():
    cfg = load_config().research
    configure_tracing(AGENT, [cfg.summarize_url])
    agent = NativeResearchAgent(cfg)
    client = ControlPlaneClient.from_env()

    async def handler(payload: dict, headers: Mapping[str, str]) -> dict:
        with tokenops_run(client=client) as bound:
            reg = bound.hop
            trace_id = reg.trace_id
            attr = bound.attr
            governor = bound.governor
            controls = bound.controls

            task = str(payload.get("task", ""))
            corpus_profile = bench_corpus_profile(payload)

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
                    governor,
                    controls,
                    attr,
                    provider=cfg.provider,
                    model=cfg.model,
                    stream_dispatch=stream_complete,
                    service=AGENT,
                )
            else:
                governed = wrap_complete(
                    governor,
                    controls,
                    attr,
                    provider=cfg.provider,
                    model=cfg.model,
                    dispatch=complete,
                    service=AGENT,
                )

            status, halt_reason, summary, findings = "completed", None, "", []
            try:
                findings = await asyncio.to_thread(
                    agent.run,
                    task,
                    corpus_profile,
                    on_step,
                    governed,
                    service=AGENT,
                )
                steps.append(
                    StepEvent(agent="research", action="delegate", detail="calling summarize agent")
                )
                remaining = governor.ledger.budget_left(
                    "run_llm_cap",
                    f"trace:{trace_id}",
                    LIFETIME,
                )
                if "run_llm_cap" in governor.ledger._budget_by_id and remaining <= 0:
                    raise Halt(
                        Action(
                            kind=ActionKind.HALT,
                            trace_id=trace_id,
                            reason="no budget remaining; refusing to delegate",
                        )
                    )
                summary, sum_tokens, sum_steps, _sum_cost = await delegate_summarize(
                    cfg.summarize_url,
                    task,
                    findings,
                )
                token_usage = token_usage.merge(sum_tokens)
                steps.extend(sum_steps)
                # Child spend is already in the shared ledger for this trace_id;
                # do not re-bill it on the parent.
            except Halt as halt:
                status, halt_reason = "halted", halt.action.reason
            except Throttled as thr:
                status, halt_reason = "throttled", thr.action.reason
            finally:
                pass

            result = RunResult(
                findings=findings, summary=summary, steps=steps, token_usage=token_usage
            )
            response = task_response(result)
            response.update(
                trace_id=trace_id, status=status, cost_micros=governor.ledger.cost_micros(trace_id)
            )
            if halt_reason:
                response["halt_reason"] = halt_reason
            response["governance_events"] = governance_events_payload(controls)
            return response

    app = create_a2a_app(
        name="research-agent",
        description="Research agent (native)",
        base_url=cfg.url,
        skills=["research"],
        handler=with_governance_errors(handler),
    )
    instrument_app(
        app,
        service=AGENT,
        intent=INTENT,
        provider=cfg.provider,
        model=cfg.model,
    )
    return app


def main() -> None:
    cfg = load_config().research
    run_server(build_app(), cfg.port)


if __name__ == "__main__":
    main()

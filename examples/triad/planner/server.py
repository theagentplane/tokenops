"""Planner A2A server — TokenOps entry agent for the triad.

Seams (Wave 1–2 happy path):
  * ControlPlaneClient.from_env — no Store(TOKENOPS_DB) in agent (§6)
  * instrument_app — RequestContext + install_crossing_hook
  * tokenops_run — register-or-join + governance in one scope
  * wrap_complete around the planner LLM
  * delegate_researcher / delegate_writer with auto header propagation
  * Child spend lands in the shared ledger (no parent cost rollup)
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

from examples.a2a.messages import bench_corpus_profile
from examples.a2a.server import create_a2a_app, run_server
from examples.a2a.tracing import configure_tracing
from examples.agents.types import StepEvent, TokenUsage
from examples.app_config import load_config
from examples.triad.client import delegate_researcher, delegate_writer
from examples.triad.messages import plan_response
from examples.triad.planner.agent import PlannerAgent
from tokenops import ControlPlaneClient, instrument_app, tokenops_run
from tokenops.capabilities import wrap_complete
from tokenops.framework import Action, ActionKind, Halt, Throttled, governance_events_payload
from tokenops.framework.ledger import LIFETIME
from tokenops.interfaces import with_governance_errors
from tokenops.providers import complete

AGENT = "planner"
INTENT = "triad_plan"


def build_app():
    cfg = load_config().planner
    configure_tracing(AGENT, [cfg.researcher_url, cfg.writer_url])
    agent = PlannerAgent(cfg)
    client = ControlPlaneClient.from_env()

    async def handler(payload: dict, headers: Mapping[str, str]) -> dict:
        # Ambient RequestContext from instrument_app; agent owns intent/mode (§1).
        with tokenops_run(client=client) as bound:
            reg = bound.hop
            trace_id = reg.trace_id
            attr = bound.attr
            governor = bound.governor
            controls = bound.controls

            goal = str(payload.get("task", ""))
            corpus_profile = bench_corpus_profile(payload)

            steps: list[StepEvent] = []
            token_usage = TokenUsage()

            def on_step(event: StepEvent) -> None:
                steps.append(event)
                token_usage.input_tokens += event.tokens.input_tokens
                token_usage.output_tokens += event.tokens.output_tokens

            governed = wrap_complete(
                governor,
                controls,
                attr,
                provider=cfg.provider,
                model=cfg.model,
                dispatch=complete,
                service=AGENT,
            )

            status, halt_reason = "completed", None
            questions: list[str] = []
            outline: list[str] = []
            findings = []
            answer = ""

            try:
                questions, outline = await asyncio.to_thread(
                    agent.run,
                    goal,
                    on_step,
                    governed,
                )
                steps.append(
                    StepEvent(
                        agent="planner",
                        action="delegate",
                        detail="calling researcher agent",
                    )
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

                findings, res_tokens, res_steps, _res_cost = await delegate_researcher(
                    cfg.researcher_url,
                    goal,
                    questions,
                    outline=outline,
                    corpus_profile=corpus_profile,
                )
                token_usage = token_usage.merge(res_tokens)
                steps.extend(res_steps)

                steps.append(
                    StepEvent(
                        agent="planner",
                        action="delegate",
                        detail="calling writer agent",
                    )
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
                            reason="no budget remaining; refusing to delegate to writer",
                        )
                    )

                answer, wr_tokens, wr_steps, _wr_cost = await delegate_writer(
                    cfg.writer_url,
                    goal,
                    findings,
                    outline=outline,
                    questions=questions,
                )
                token_usage = token_usage.merge(wr_tokens)
                steps.extend(wr_steps)
            except Halt as halt:
                status, halt_reason = "halted", halt.action.reason
            except Throttled as thr:
                status, halt_reason = "throttled", thr.action.reason
            finally:
                pass

            response = plan_response(
                questions=questions,
                outline=outline,
                findings=findings,
                answer=answer,
                token_usage=token_usage,
                steps=steps,
            )
            response.update(
                trace_id=trace_id,
                status=status,
                cost_micros=governor.ledger.cost_micros(trace_id),
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
    instrument_app(
        app,
        service=AGENT,
        intent=INTENT,
        provider=cfg.provider,
        model=cfg.model,
    )
    return app


def main() -> None:
    cfg = load_config().planner
    run_server(build_app(), cfg.port)


if __name__ == "__main__":
    main()

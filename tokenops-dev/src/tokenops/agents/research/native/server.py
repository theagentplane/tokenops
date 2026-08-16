from __future__ import annotations

import asyncio
import os
import time

from tokenops.a2a.client import delegate_summarize
from tokenops.a2a.messages import task_response
from tokenops.a2a.server import create_a2a_app, run_server
from tokenops.agents.research.native.agent import NativeResearchAgent
from tokenops.agents.types import RunResult, StepEvent, TokenUsage
from tokenops.config import load_config
from tokenops.control import (
    Attribution,
    ApplyControls,
    Halt,
    Observation,
    build_governor,
    make_on_step,
    wrap_complete,
)
from tokenops.control.engine import Throttled
from tokenops.control.models import RunRecord
from tokenops.control.pricing import build_price_book
from tokenops.control.store import Store, new_id
from tokenops.providers import complete

AGENT = "research"


def build_app():
    cfg = load_config().research
    agent = NativeResearchAgent(cfg)
    # Process singletons (shared with the other server + the UIs via the same file).
    store = Store(os.environ.get("TOKENOPS_DB", "tokenops.db"))
    price = build_price_book()

    async def handler(payload: dict) -> dict:
        task = str(payload.get("task", ""))
        corpus_profile = payload.get("corpus_profile", "healthy")
        user = str(payload.get("user", "ui"))
        run_id = str(payload.get("run_id") or new_id("run"))

        attr = Attribution(user=user, agent=AGENT, run_id=run_id,
                           tags={"corpus_profile": str(corpus_profile)})
        governor = build_governor(store.governance_config_for(AGENT), price, ApplyControls())
        controls = governor.controls
        governor.ledger.open_run(run_id)
        store.create_run(RunRecord(run_id=run_id, agent=AGENT, status="running",
                                   task=task, corpus_profile=str(corpus_profile),
                                   started_at=time.time()))

        steps: list[StepEvent] = []
        token_usage = TokenUsage()
        record = make_on_step(governor, attr, provider=cfg.provider, model=cfg.model)

        def on_step(event: StepEvent) -> None:
            steps.append(event)  # accumulate for the response first, so a Halt keeps partials
            token_usage.input_tokens += event.tokens.input_tokens
            token_usage.output_tokens += event.tokens.output_tokens
            record(event)  # governance observe — may raise Halt

        governed = wrap_complete(governor, controls, attr, provider=cfg.provider,
                                 model=cfg.model, dispatch=complete)

        status, halt_reason, summary, findings = "completed", None, "", []
        try:
            findings = await asyncio.to_thread(agent.run, task, corpus_profile, on_step, governed)
            steps.append(StepEvent(agent="research", action="delegate", detail="calling summarize agent"))
            summary, sum_tokens, sum_steps, sum_cost = await delegate_summarize(
                cfg.summarize_url, task, findings, parent_run=run_id
            )
            token_usage = token_usage.merge(sum_tokens)
            steps.extend(sum_steps)
            # Roll the child's cost into the parent budget (may itself trip a budget HALT).
            governor.observe(Observation(attr=attr, node_type="delegate",
                                         boundary_id="delegate_summarize", ts=time.time(),
                                         rolled_up_cost_micros=sum_cost))
        except Halt as halt:
            status, halt_reason = "halted", halt.action.reason
        except Throttled as thr:
            status, halt_reason = "throttled", thr.action.reason
        finally:
            store.update_run(run_id, status=status, halt_reason=halt_reason,
                             cost_micros=governor.ledger.cost_micros(run_id),
                             steps=governor.ledger.step_count(run_id), ended_at=time.time())

        result = RunResult(findings=findings, summary=summary, steps=steps, token_usage=token_usage)
        response = task_response(result)
        response.update(run_id=run_id, status=status,
                        cost_micros=governor.ledger.cost_micros(run_id))
        if halt_reason:
            response["halt_reason"] = halt_reason
        return response

    return create_a2a_app(
        name="research-agent",
        description="Research agent (native)",
        base_url=cfg.url,
        skills=["research"],
        handler=handler,
    )


def main() -> None:
    cfg = load_config().research
    run_server(build_app(), cfg.port)


if __name__ == "__main__":
    main()

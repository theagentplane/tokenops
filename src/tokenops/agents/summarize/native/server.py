from __future__ import annotations

import asyncio
import os
import time

from tokenops.a2a.messages import parse_findings, summarize_response
from tokenops.a2a.server import create_a2a_app, run_server
from tokenops.agents.summarize.native.agent import NativeSummarizeAgent
from tokenops.agents.types import StepEvent, TokenUsage
from tokenops.config import load_config
from tokenops.control import (
    Attribution,
    ApplyControls,
    Halt,
    build_governor,
    make_on_step,
    wrap_complete,
)
from tokenops.control.engine import Throttled
from tokenops.control.models import RunRecord
from tokenops.control.pricing import build_price_book
from tokenops.control.store import Store, new_id
from tokenops.providers import complete

AGENT = "summarize"


def build_app():
    cfg = load_config().summarize
    agent = NativeSummarizeAgent(cfg)
    store = Store(os.environ.get("TOKENOPS_DB", "tokenops.db"))
    price = build_price_book()

    async def handler(payload: dict) -> dict:
        task = str(payload.get("task", ""))
        findings = parse_findings(payload.get("findings", []))
        user = str(payload.get("user", "ui"))
        parent_run = payload.get("parent_run")
        run_id = new_id("run")  # the summarize child run, linked to the research parent

        attr = Attribution(user=user, agent=AGENT, run_id=run_id, parent_run=parent_run)
        governor = build_governor(store.governance_config_for(AGENT), price, ApplyControls())
        controls = governor.controls
        governor.ledger.open_run(run_id, parent_run)
        store.create_run(RunRecord(run_id=run_id, agent=AGENT, status="running",
                                   parent_run=parent_run, task=task, started_at=time.time()))

        steps: list[StepEvent] = []
        token_usage = TokenUsage()
        record = make_on_step(governor, attr, provider=cfg.provider, model=cfg.model)

        def on_step(event: StepEvent) -> None:
            steps.append(event)
            token_usage.input_tokens += event.tokens.input_tokens
            token_usage.output_tokens += event.tokens.output_tokens
            record(event)

        governed = wrap_complete(governor, controls, attr, provider=cfg.provider,
                                 model=cfg.model, dispatch=complete)

        status, halt_reason, summary = "completed", None, ""
        try:
            summary = await asyncio.to_thread(agent.run, task, findings, on_step, governed)
        except Halt as halt:
            status, halt_reason = "halted", halt.action.reason
        except Throttled as thr:
            status, halt_reason = "throttled", thr.action.reason
        finally:
            store.update_run(run_id, status=status, halt_reason=halt_reason,
                             cost_micros=governor.ledger.cost_micros(run_id),
                             steps=governor.ledger.step_count(run_id), ended_at=time.time())

        response = summarize_response(summary, token_usage, steps,
                                      cost_micros=governor.ledger.cost_micros(run_id))
        response.update(run_id=run_id, status=status)
        if halt_reason:
            response["halt_reason"] = halt_reason
        return response

    return create_a2a_app(
        name="summarize-agent",
        description="Summarize agent (native)",
        base_url=cfg.url,
        skills=["summarize"],
        handler=handler,
    )


def main() -> None:
    cfg = load_config().summarize
    run_server(build_app(), cfg.port)


if __name__ == "__main__":
    main()

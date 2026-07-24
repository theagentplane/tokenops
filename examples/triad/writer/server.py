"""Writer A2A server — tokenops_run + wrap_complete (shared ledger)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping

from examples.a2a.messages import parse_findings
from examples.a2a.server import create_a2a_app, run_server
from examples.agents.types import StepEvent, TokenUsage
from examples.app_config import load_config
from examples.triad.messages import parse_outline, parse_questions, write_response
from examples.triad.writer.agent import WriterAgent
from tokenops import ControlPlaneClient, instrument_app, tokenops_run
from tokenops.control import (
    Halt,
    with_governance_errors,
    wrap_complete,
)
from tokenops.control.engine import Throttled
from tokenops.control.models import RunRecord
from tokenops.providers import complete

AGENT = "writer"


def build_app():
    cfg = load_config().writer
    agent = WriterAgent(cfg)
    client = ControlPlaneClient.from_env()

    async def handler(payload: dict, headers: Mapping[str, str]) -> dict:
        with tokenops_run(client=client) as bound:
            reg = bound.registration
            run_id = reg.run_id
            attr = bound.attr
            governor = bound.governor
            controls = bound.controls

            task = str(payload.get("task", ""))
            findings = parse_findings(payload.get("findings", []))
            outline = parse_outline(payload.get("outline", []))
            questions = parse_questions(payload.get("questions", []))
            parent_span = headers.get("X-TokenOps-Parent-Span-Id") or payload.get("parent_run")

            client.create_run(
                RunRecord(
                    run_id=run_id,
                    agent=AGENT,
                    status="running",
                    parent_span=parent_span,
                    task=task,
                    started_at=time.time(),
                )
            )

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

            status, halt_reason, answer = "completed", None, ""
            try:
                answer = await asyncio.to_thread(
                    agent.run,
                    task,
                    findings,
                    outline,
                    questions,
                    on_step,
                    governed,
                )
            except Halt as halt:
                status, halt_reason = "halted", halt.action.reason
            except Throttled as thr:
                status, halt_reason = "throttled", thr.action.reason
            finally:
                client.update_run(
                    run_id,
                    status=status,
                    halt_reason=halt_reason,
                    cost_micros=governor.ledger.cost_micros(run_id),
                    steps=governor.ledger.step_count(run_id),
                    ended_at=time.time(),
                )

            response = write_response(
                answer,
                token_usage,
                steps,
                cost_micros=governor.ledger.cost_micros(run_id),
            )
            response.update(run_id=run_id, status=status)
            if halt_reason:
                response["halt_reason"] = halt_reason
            return response

    app = create_a2a_app(
        name="writer-agent",
        description="Triad writer agent (TokenOps)",
        base_url=cfg.url,
        skills=["write"],
        handler=with_governance_errors(handler),
    )
    instrument_app(
        app,
        service=AGENT,
        provider=cfg.provider,
        model=cfg.model,
    )
    return app


def main() -> None:
    cfg = load_config().writer
    run_server(build_app(), cfg.port)


if __name__ == "__main__":
    main()

"""Researcher A2A server — tools + wrap_complete + crossing hook."""

from __future__ import annotations

import asyncio
import os
import time
from typing import Mapping

from examples.a2a.messages import bench_corpus_profile
from examples.a2a.server import create_a2a_app, run_server
from examples.agents.types import StepEvent, TokenUsage
from examples.triad.messages import parse_outline, parse_questions, research_response
from examples.triad.researcher.agent import ResearcherAgent

from examples.app_config import load_config
from tokenops.control import (
    ApplyControls,
    PreviewControls,
    Halt,
    build_attribution,
    build_governor,
    downstream_run_scope,
    install_crossing_hook,
    with_governance_errors,
    wrap_complete,
)
from tokenops.control.context import current_registration, governance_scope
from tokenops.control.engine import Throttled
from tokenops.control.models import GovernanceMode, RunRecord
from tokenops.control.pricing import build_price_book
from tokenops.control.store import Store
from tokenops.providers import complete

AGENT = "researcher"


def build_app():
    cfg = load_config().researcher
    agent = ResearcherAgent(cfg)
    store = Store(os.environ.get("TOKENOPS_DB", "tokenops.db"))
    price = build_price_book()

    async def handler(payload: dict, headers: Mapping[str, str]) -> dict:
        with downstream_run_scope(store, headers=headers, service=AGENT):
            reg = current_registration()
            assert reg is not None
            run_id = reg.run_id
            attr = build_attribution(reg, service=AGENT)
            mode = reg.mode

            task = str(payload.get("task", ""))
            questions = parse_questions(payload.get("questions", []))
            parse_outline(payload.get("outline", []))  # reserved for richer researcher prompts
            corpus_profile = bench_corpus_profile(payload)
            parent_span = headers.get("X-TokenOps-Parent-Span-Id") or payload.get("parent_run")

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
                governor, controls, attr, provider=cfg.provider, model=cfg.model,
                dispatch=complete, service=AGENT,
            )

            status, halt_reason, findings = "completed", None, []
            with governance_scope(governor, attr, provider=cfg.provider, model=cfg.model):
                try:
                    findings = await asyncio.to_thread(
                        agent.run, task, questions, corpus_profile, on_step, governed,
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

            response = research_response(
                findings, token_usage, steps, cost_micros=governor.ledger.cost_micros(run_id),
            )
            response.update(run_id=run_id, status=status)
            if halt_reason:
                response["halt_reason"] = halt_reason
            return response

    app = create_a2a_app(
        name="researcher-agent",
        description="Triad researcher agent (tools + TokenOps)",
        base_url=cfg.url,
        skills=["research"],
        handler=with_governance_errors(handler),
    )
    install_crossing_hook()
    return app


def main() -> None:
    cfg = load_config().researcher
    run_server(build_app(), cfg.port)


if __name__ == "__main__":
    main()

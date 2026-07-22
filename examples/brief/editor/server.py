"""Editor A2A server — LangChain + downstream_run_scope + wrap_complete."""

from __future__ import annotations

import asyncio
import os
import time
from typing import Mapping

from examples.a2a.messages import parse_findings
from examples.a2a.server import create_a2a_app, run_server
from examples.agents.types import StepEvent, TokenUsage
from examples.app_config import load_config
from examples.brief.editor.agent import EditorAgent
from examples.brief.langchain_bridge import GovernedChatModel, make_langchain_dispatch
from examples.brief.messages import edit_response, parse_angles, parse_sections
from tokenops.control import (
    ApplyControls,
    Halt,
    PreviewControls,
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

AGENT = "editor"


def build_app():
    cfg = load_config().editor
    agent = EditorAgent(cfg)
    store = Store(os.environ.get("TOKENOPS_DB", "tokenops.db"))
    price = build_price_book()

    async def handler(payload: dict, headers: Mapping[str, str]) -> dict:
        with downstream_run_scope(store, headers=headers, service=AGENT):
            reg = current_registration()
            assert reg is not None
            run_id = reg.run_id
            attr = build_attribution(reg, service=AGENT)
            mode = reg.mode

            topic = str(payload.get("task", ""))
            findings = parse_findings(payload.get("findings", []))
            sections = parse_sections(payload.get("sections", []))
            angles = parse_angles(payload.get("angles", []))
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
                    task=topic,
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
                dispatch=make_langchain_dispatch(cfg.provider, cfg.model), service=AGENT,
            )
            llm = GovernedChatModel(governed, provider=cfg.provider, model=cfg.model)

            status, halt_reason, brief = "completed", None, ""
            with governance_scope(governor, attr, provider=cfg.provider, model=cfg.model):
                try:
                    brief = await asyncio.to_thread(
                        agent.run, topic, findings, sections, angles, on_step, llm,
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

            response = edit_response(
                brief, token_usage, steps, cost_micros=governor.ledger.cost_micros(run_id),
            )
            response.update(run_id=run_id, status=status)
            if halt_reason:
                response["halt_reason"] = halt_reason
            return response

    app = create_a2a_app(
        name="editor-agent",
        description="Brief editor agent (TokenOps)",
        base_url=cfg.url,
        skills=["edit"],
        handler=with_governance_errors(handler),
    )
    install_crossing_hook()
    return app


def main() -> None:
    cfg = load_config().editor
    run_server(build_app(), cfg.port)


if __name__ == "__main__":
    main()

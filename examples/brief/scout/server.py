"""Scout A2A server — TokenOps entry for LangChain brief stack.

LLM calls: LangChain ChatOpenAI/Anthropic → wrap_complete → GovernedChatModel.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Mapping

from chronicle.session import reset_session
from examples.a2a.messages import bench_corpus_profile
from examples.a2a.server import create_a2a_app, run_server
from examples.agents.types import StepEvent, TokenUsage
from examples.app_config import load_config
from examples.brief.client import delegate_analyst, delegate_editor
from examples.brief.messages import scout_response
from examples.brief.langchain_bridge import GovernedChatModel, make_langchain_dispatch
from examples.brief.scout.agent import ScoutAgent
from tokenops.control import (
    Action,
    ActionKind,
    ApplyControls,
    Halt,
    PreviewControls,
    build_attribution,
    build_governor,
    entry_task_run_scope,
    governance_events_payload,
    halt_detector_from_events,
    install_crossing_hook,
    mount_run_registration,
    should_mount_run_registration,
    with_governance_errors,
    wrap_complete,
)
from tokenops.control.context import current_registration, governance_scope
from tokenops.control.engine import Throttled
from tokenops.control.ledger import LIFETIME
from tokenops.control.models import GovernanceMode, RunRecord
from tokenops.control.pricing import build_price_book
from tokenops.control.store import Store

AGENT = "scout"


def build_app():
    cfg = load_config().scout
    agent = ScoutAgent(cfg)
    store = Store(os.environ.get("TOKENOPS_DB", "tokenops.db"))
    price = build_price_book()

    async def handler(payload: dict, headers: Mapping[str, str]) -> dict:
        with entry_task_run_scope(store, headers=headers, payload=payload, service=AGENT):
            reg = current_registration()
            assert reg is not None
            run_id = reg.run_id
            reset_session().begin_trace(run_id)
            attr = build_attribution(reg, service=AGENT)
            mode = reg.mode

            topic = str(payload.get("task", ""))
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
                    task=topic,
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
                dispatch=make_langchain_dispatch(cfg.provider, cfg.model), service=AGENT,
            )
            llm = GovernedChatModel(governed, provider=cfg.provider, model=cfg.model)

            status, halt_reason = "completed", None
            angles: list[str] = []
            sections: list[str] = []
            findings = []
            brief = ""

            with governance_scope(governor, attr, provider=cfg.provider, model=cfg.model):
                try:
                    angles, sections = await asyncio.to_thread(
                        agent.run, topic, on_step, llm,
                    )
                    steps.append(
                        StepEvent(agent="scout", action="delegate", detail="calling analyst agent")
                    )
                    remaining = governor.ledger.budget_left(
                        "run_llm_cap", f"run:{run_id}", LIFETIME,
                    )
                    if "run_llm_cap" in governor.ledger._budget_by_id and remaining <= 0:
                        raise Halt(Action(
                            kind=ActionKind.HALT, run_id=run_id,
                            reason="no budget remaining; refusing to delegate",
                        ))

                    findings, an_tokens, an_steps, _ = await delegate_analyst(
                        cfg.analyst_url,
                        topic,
                        angles,
                        sections=sections,
                        corpus_profile=corpus_profile,
                    )
                    token_usage = token_usage.merge(an_tokens)
                    steps.extend(an_steps)

                    steps.append(
                        StepEvent(agent="scout", action="delegate", detail="calling editor agent")
                    )
                    remaining = governor.ledger.budget_left(
                        "run_llm_cap", f"run:{run_id}", LIFETIME,
                    )
                    if "run_llm_cap" in governor.ledger._budget_by_id and remaining <= 0:
                        raise Halt(Action(
                            kind=ActionKind.HALT, run_id=run_id,
                            reason="no budget remaining; refusing to delegate to editor",
                        ))

                    brief, ed_tokens, ed_steps, _ = await delegate_editor(
                        cfg.editor_url,
                        topic,
                        findings,
                        sections=sections,
                        angles=angles,
                    )
                    token_usage = token_usage.merge(ed_tokens)
                    steps.extend(ed_steps)
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

            response = scout_response(
                angles=angles,
                sections=sections,
                findings=findings,
                brief=brief,
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
        name="scout-agent",
        description="Brief scout agent (TokenOps entry)",
        base_url=cfg.url,
        skills=["scout"],
        handler=with_governance_errors(handler),
    )
    if should_mount_run_registration():
        mount_run_registration(app, store)
    install_crossing_hook()
    return app


def main() -> None:
    cfg = load_config().scout
    run_server(build_app(), cfg.port)


if __name__ == "__main__":
    main()

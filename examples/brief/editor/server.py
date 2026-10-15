"""Editor A2A server — LangChain + tokenops_run + wrap_complete."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

from examples.a2a.messages import parse_findings
from examples.a2a.server import create_a2a_app, run_server
from examples.agents.types import StepEvent, TokenUsage
from examples.app_config import load_config
from examples.brief.editor.agent import EditorAgent
from examples.brief.langchain_bridge import GovernedChatModel, make_langchain_dispatch
from examples.brief.messages import edit_response, parse_angles, parse_sections
from tokenops import ControlPlaneClient, instrument_app, tokenops_run
from tokenops.control import (
    Halt,
    with_governance_errors,
    wrap_complete,
)
from tokenops.control.engine import Throttled

AGENT = "editor"


def build_app():
    cfg = load_config().editor
    agent = EditorAgent(cfg)
    client = ControlPlaneClient.from_env()

    async def handler(payload: dict, headers: Mapping[str, str]) -> dict:
        with tokenops_run(client=client) as bound:
            reg = bound.hop
            trace_id = reg.trace_id
            attr = bound.attr
            governor = bound.governor
            controls = bound.controls

            topic = str(payload.get("task", ""))
            findings = parse_findings(payload.get("findings", []))
            sections = parse_sections(payload.get("sections", []))
            angles = parse_angles(payload.get("angles", []))

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
                dispatch=make_langchain_dispatch(cfg.provider, cfg.model),
                service=AGENT,
            )
            llm = GovernedChatModel(governed, provider=cfg.provider, model=cfg.model)

            status, halt_reason, brief = "completed", None, ""
            try:
                brief = await asyncio.to_thread(
                    agent.run,
                    topic,
                    findings,
                    sections,
                    angles,
                    on_step,
                    llm,
                )
            except Halt as halt:
                status, halt_reason = "halted", halt.action.reason
            except Throttled as thr:
                status, halt_reason = "throttled", thr.action.reason
            finally:
                pass

            response = edit_response(
                brief,
                token_usage,
                steps,
                cost_micros=governor.ledger.cost_micros(trace_id),
            )
            response.update(trace_id=trace_id, status=status)
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
    instrument_app(
        app,
        service=AGENT,
        provider=cfg.provider,
        model=cfg.model,
    )
    return app


def main() -> None:
    cfg = load_config().editor
    run_server(build_app(), cfg.port)


if __name__ == "__main__":
    main()

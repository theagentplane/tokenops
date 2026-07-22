from __future__ import annotations

import asyncio
import os
import time
from typing import Mapping

from examples.a2a.client import delegate_summarize
from examples.a2a.messages import bench_corpus_profile, task_response
from examples.a2a.server import create_a2a_app, run_server
from examples.agents.research.native.agent import NativeResearchAgent
from examples.agents.types import RunResult, StepEvent, TokenUsage
from chronicle.session import reset_session

from examples.app_config import load_config
from tokenops.control import (
    ApplyControls,
    PreviewControls,
    Halt,
    Action,
    ActionKind,
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
    wrap_stream,
)
from tokenops.control.context import current_registration, governance_scope
from tokenops.control.engine import Throttled
from tokenops.control.ledger import LIFETIME
from tokenops.control.models import GovernanceMode, RunRecord
from tokenops.control.trajectory import enqueue_completed_run, schedule_trajectory_drain
from tokenops.control.pricing import build_price_book
from tokenops.control.store import Store
from tokenops.providers import complete, stream_complete

AGENT = "research"


def build_app():
    cfg = load_config().research
    agent = NativeResearchAgent(cfg)
    store = Store(os.environ.get("TOKENOPS_DB", "tokenops.db"))
    price = build_price_book()

    async def handler(payload: dict, headers: Mapping[str, str]) -> dict:
        # Entry agent: UI may omit run_id — register via ControlPlaneClient / plane.
        with entry_task_run_scope(store, headers=headers, payload=payload, service=AGENT):
            reg = current_registration()
            assert reg is not None
            run_id = reg.run_id
            reset_session().begin_trace(run_id)
            attr = build_attribution(reg, service=AGENT)
            mode = reg.mode

            task = str(payload.get("task", ""))
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
                    summary, sum_tokens, sum_steps, _sum_cost = await delegate_summarize(
                        cfg.summarize_url,
                        task,
                        findings,
                    )
                    token_usage = token_usage.merge(sum_tokens)
                    steps.extend(sum_steps)
                    # Child spend is already in the shared ledger for this run_id;
                    # do not re-bill it on the parent.
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
                    rec = store.get_run(run_id)
                    if rec is not None:
                        gov_cfg = store.governance_config_for(AGENT).get("governance", {})
                        hint_params = (gov_cfg.get("policies") or {}).get("trajectory_hint")
                        if enqueue_completed_run(
                            store,
                            rec=rec,
                            registration=reg,
                            agent=AGENT,
                            window=governor.ledger.window(run_id),
                            policy_params=hint_params,
                        ):
                            p = dict(hint_params or {})
                            schedule_trajectory_drain(
                                store,
                                max_age_days=int(p.get("max_age_days", 30)),
                                max_entries_per_scope=int(p.get("max_entries_per_scope", 500)),
                            )

            result = RunResult(findings=findings, summary=summary, steps=steps, token_usage=token_usage)
            response = task_response(result)
            response.update(run_id=run_id, status=status, cost_micros=governor.ledger.cost_micros(run_id))
            if halt_reason:
                response["halt_reason"] = halt_reason
            gov_actions = (
                controls.actions
                if isinstance(controls, PreviewControls)
                else controls.event_log
            )
            response["governance_events"] = governance_events_payload(controls)
            return response

    app = create_a2a_app(
        name="research-agent",
        description="Research agent (native)",
        base_url=cfg.url,
        skills=["research"],
        handler=with_governance_errors(handler),
    )
    # When TOKENOPS_URL points at the standalone plane, registration lives there —
    # do not double-mount /v1/runs on the agent. Embedded / no-URL keeps local mount
    # for pytest TestClient and single-process local runs.
    if should_mount_run_registration():
        mount_run_registration(app, store)
    install_crossing_hook()
    return app


def main() -> None:
    cfg = load_config().research
    run_server(build_app(), cfg.port)


if __name__ == "__main__":
    main()

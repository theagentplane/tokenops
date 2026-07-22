"""HTTP client for the triad bench (Planner entry + A2A delegates)."""

from __future__ import annotations

import os

from examples.a2a.messages import parse_findings, parse_steps, parse_token_usage, task_request
from examples.a2a.server import post_task, post_task_sync
from examples.agents.types import Finding, RunResult, StepEvent, TokenUsage
from examples.triad.messages import research_request, write_request
from tokenops.control.client import ControlPlaneClient
from tokenops.control.context import PARENT_SPAN_ID_HEADER, RUN_ID_HEADER
from tokenops.control.models import GovernanceMode


def _register(
    *,
    intent: str = "",
    user_dims: dict[str, str] | None = None,
    mode: GovernanceMode | str | None = None,
) -> dict:
    return ControlPlaneClient.from_env().register_run(
        intent=intent, user_dims=user_dims or {}, mode=mode,
    )


def _parse_result(data: dict) -> RunResult:
    return RunResult(
        findings=parse_findings(data.get("findings", [])),
        summary=str(data.get("answer") or data.get("summary", "")),
        steps=parse_steps(data.get("steps", [])),
        token_usage=parse_token_usage(data.get("token_usage")),
    )


def submit_goal_sync(
    planner_url: str,
    goal: str,
    *,
    corpus_profile: str = "healthy",
    intent: str = "",
    user_dims: dict[str, str] | None = None,
) -> RunResult:
    result, _meta = submit_goal_sync_with_meta(
        planner_url,
        goal,
        corpus_profile=corpus_profile,
        intent=intent,
        user_dims=user_dims,
    )
    return result


def submit_goal_sync_with_meta(
    planner_url: str,
    goal: str,
    *,
    corpus_profile: str = "healthy",
    intent: str = "",
    user_dims: dict[str, str] | None = None,
    governance_mode: GovernanceMode = GovernanceMode.ENFORCE,
) -> tuple[RunResult, dict[str, object]]:
    """POST the goal to the Planner entry agent (UI path).

    The Planner registers the run on the control plane when ``X-TokenOps-Run-Id``
    is absent — clients should not call ``/v1/runs`` themselves for the triad UI.
    """
    if not (os.environ.get("TOKENOPS_URL") or "").strip() and os.environ.get("TOKENOPS_EMBEDDED") != "1":
        os.environ.setdefault("TOKENOPS_EMBEDDED", "1")
    payload = task_request(task=goal, bench={"corpus_profile": corpus_profile}, intent=intent)
    if user_dims:
        payload["user_dims"] = user_dims
    payload["mode"] = (
        governance_mode.value if isinstance(governance_mode, GovernanceMode) else governance_mode
    )
    # No run_id header — entry agent opens the run.
    data = post_task_sync(planner_url, payload, headers=None)
    result = _parse_result(data)
    meta: dict[str, object] = {
        "status": data.get("status"),
        "halt_reason": data.get("halt_reason"),
        "cost_micros": int(data.get("cost_micros", 0)),
        "governance_events": data.get("governance_events") or [],
        "run_id": data.get("run_id"),
        "questions": data.get("questions") or [],
        "outline": data.get("outline") or [],
    }
    return result, meta


async def delegate_researcher(
    researcher_url: str,
    task: str,
    questions: list[str],
    *,
    run_id: str | None = None,
    outline: list[str] | None = None,
    corpus_profile: str = "healthy",
    parent_span_id: str | None = None,
) -> tuple[list[Finding], TokenUsage, list[StepEvent], int]:
    """Delegate to researcher. Headers come from ambient context when omitted."""
    payload = research_request(
        task, questions, outline=outline, bench={"corpus_profile": corpus_profile},
    )
    headers: dict[str, str] = {}
    if run_id:
        headers[RUN_ID_HEADER] = run_id
    if parent_span_id:
        headers[PARENT_SPAN_ID_HEADER] = parent_span_id
    # post_task merges ambient propagation (run_id + current span as parent).
    data = await post_task(researcher_url, payload, headers=headers or None)
    return (
        parse_findings(data.get("findings", [])),
        parse_token_usage(data.get("token_usage")),
        parse_steps(data.get("steps", [])),
        int(data.get("cost_micros", 0)),
    )


async def delegate_writer(
    writer_url: str,
    task: str,
    findings: list[Finding],
    *,
    run_id: str | None = None,
    outline: list[str] | None = None,
    questions: list[str] | None = None,
    parent_span_id: str | None = None,
) -> tuple[str, TokenUsage, list[StepEvent], int]:
    """Delegate to writer. Headers come from ambient context when omitted."""
    payload = write_request(task, findings, outline=outline, questions=questions)
    headers: dict[str, str] = {}
    if run_id:
        headers[RUN_ID_HEADER] = run_id
    if parent_span_id:
        headers[PARENT_SPAN_ID_HEADER] = parent_span_id
    data = await post_task(writer_url, payload, headers=headers or None)
    answer = str(data.get("answer") or data.get("summary", ""))
    return (
        answer,
        parse_token_usage(data.get("token_usage")),
        parse_steps(data.get("steps", [])),
        int(data.get("cost_micros", 0)),
    )

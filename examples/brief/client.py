"""HTTP client for the brief stack (Scout entry + A2A delegates)."""

from __future__ import annotations

import os

from examples.a2a.messages import parse_findings, parse_steps, parse_token_usage, task_request
from examples.a2a.server import post_task, post_task_sync
from examples.agents.types import Finding, RunResult, StepEvent, TokenUsage
from examples.brief.messages import analyze_request, edit_request
from tokenops.control.context import PARENT_SPAN_ID_HEADER, RUN_ID_HEADER
from tokenops.control.models import GovernanceMode


def _parse_result(data: dict) -> RunResult:
    return RunResult(
        findings=parse_findings(data.get("findings", [])),
        summary=str(data.get("brief") or data.get("answer") or data.get("summary", "")),
        steps=parse_steps(data.get("steps", [])),
        token_usage=parse_token_usage(data.get("token_usage")),
    )


def submit_brief_sync(
    scout_url: str,
    topic: str,
    *,
    corpus_profile: str = "healthy",
    intent: str = "",
    user_dims: dict[str, str] | None = None,
) -> RunResult:
    result, _meta = submit_brief_sync_with_meta(
        scout_url,
        topic,
        corpus_profile=corpus_profile,
        intent=intent,
        user_dims=user_dims,
    )
    return result


def submit_brief_sync_with_meta(
    scout_url: str,
    topic: str,
    *,
    corpus_profile: str = "healthy",
    intent: str = "",
    user_dims: dict[str, str] | None = None,
    governance_mode: GovernanceMode = GovernanceMode.ENFORCE,
) -> tuple[RunResult, dict[str, object]]:
    """POST the topic to Scout (entry). Scout registers the run when run_id is omitted."""
    if not (os.environ.get("TOKENOPS_URL") or "").strip() and os.environ.get("TOKENOPS_EMBEDDED") != "1":
        os.environ.setdefault("TOKENOPS_EMBEDDED", "1")
    payload = task_request(task=topic, bench={"corpus_profile": corpus_profile}, intent=intent)
    if user_dims:
        payload["user_dims"] = user_dims
    payload["mode"] = (
        governance_mode.value if isinstance(governance_mode, GovernanceMode) else governance_mode
    )
    data = post_task_sync(scout_url, payload, headers=None)
    result = _parse_result(data)
    meta: dict[str, object] = {
        "status": data.get("status"),
        "halt_reason": data.get("halt_reason"),
        "cost_micros": int(data.get("cost_micros", 0)),
        "governance_events": data.get("governance_events") or [],
        "run_id": data.get("run_id"),
        "angles": data.get("angles") or [],
        "sections": data.get("sections") or [],
    }
    return result, meta


async def delegate_analyst(
    analyst_url: str,
    topic: str,
    angles: list[str],
    *,
    run_id: str | None = None,
    sections: list[str] | None = None,
    corpus_profile: str = "healthy",
    parent_span_id: str | None = None,
) -> tuple[list[Finding], TokenUsage, list[StepEvent], int]:
    payload = analyze_request(
        topic, angles, sections=sections, bench={"corpus_profile": corpus_profile},
    )
    headers: dict[str, str] = {}
    if run_id:
        headers[RUN_ID_HEADER] = run_id
    if parent_span_id:
        headers[PARENT_SPAN_ID_HEADER] = parent_span_id
    data = await post_task(analyst_url, payload, headers=headers or None)
    return (
        parse_findings(data.get("findings", [])),
        parse_token_usage(data.get("token_usage")),
        parse_steps(data.get("steps", [])),
        int(data.get("cost_micros", 0)),
    )


async def delegate_editor(
    editor_url: str,
    topic: str,
    findings: list[Finding],
    *,
    run_id: str | None = None,
    sections: list[str] | None = None,
    angles: list[str] | None = None,
    parent_span_id: str | None = None,
) -> tuple[str, TokenUsage, list[StepEvent], int]:
    payload = edit_request(topic, findings, sections=sections, angles=angles)
    headers: dict[str, str] = {}
    if run_id:
        headers[RUN_ID_HEADER] = run_id
    if parent_span_id:
        headers[PARENT_SPAN_ID_HEADER] = parent_span_id
    data = await post_task(editor_url, payload, headers=headers or None)
    brief = str(data.get("brief") or data.get("answer") or data.get("summary", ""))
    return (
        brief,
        parse_token_usage(data.get("token_usage")),
        parse_steps(data.get("steps", [])),
        int(data.get("cost_micros", 0)),
    )

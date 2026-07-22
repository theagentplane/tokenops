"""Researcher tools with Chronicle @boundary — TokenOps observes via crossing hook."""

from __future__ import annotations

from typing import Callable

from examples.agents.research.tools import core
from examples.agents.types import CorpusProfile, StepCallback, StepEvent
from chronicle import InputState, boundary


def make_search_tool(
    profile: CorpusProfile,
    *,
    on_step: StepCallback | None = None,
) -> Callable[[str], core.SearchResult]:
    @boundary(
        "search",
        kind="tool",
        extract_input=lambda query: InputState(
            messages=[], graph_state={"name": "search", "args": {"query": query}}
        ),
    )
    def invoke(query: str) -> core.SearchResult:
        result = core.search(query, profile)
        if on_step:
            on_step(
                StepEvent(
                    agent="researcher",
                    action="search",
                    detail=result.snippet[:120],
                    query=query,
                    completeness=result.completeness,
                )
            )
        return result

    return invoke


def make_fetch_tool(
    profile: CorpusProfile,
    *,
    on_step: StepCallback | None = None,
) -> Callable[[str], core.SearchResult]:
    """Fetch is a second tool seam (same corpus/search backend) for tool_reject demos."""

    @boundary(
        "fetch",
        kind="tool",
        extract_input=lambda query: InputState(
            messages=[], graph_state={"name": "fetch", "args": {"query": query}}
        ),
    )
    def invoke(query: str) -> core.SearchResult:
        result = core.search(query, profile)
        if on_step:
            on_step(
                StepEvent(
                    agent="researcher",
                    action="fetch",
                    detail=result.snippet[:120],
                    query=query,
                    completeness=result.completeness,
                )
            )
        return result

    return invoke

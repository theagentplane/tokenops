"""LangChain analyst tools — StructuredTool over Chronicle @boundary (TokenOps observe)."""

from __future__ import annotations

from chronicle import InputState, boundary
from langchain_core.tools import StructuredTool

from examples.agents.research.tools import core
from examples.agents.types import CorpusProfile, StepCallback, StepEvent


def make_search_tool(
    profile: CorpusProfile,
    *,
    on_step: StepCallback | None = None,
) -> StructuredTool:
    @boundary(
        "search",
        kind="tool",
        extract_input=lambda query: InputState(
            messages=[], graph_state={"name": "search", "args": {"query": query}}
        ),
    )
    def search_impl(query: str) -> dict:
        result = core.search(query, profile)
        if on_step:
            on_step(
                StepEvent(
                    agent="analyst",
                    action="search",
                    detail=result.snippet[:120],
                    query=query,
                    completeness=result.completeness,
                )
            )
        return {
            "query": result.query,
            "snippet": result.snippet,
            "completeness": result.completeness,
        }

    return StructuredTool.from_function(
        search_impl,
        name="search",
        description="Search the research corpus for evidence about an angle.",
    )


def make_fetch_tool(
    profile: CorpusProfile,
    *,
    on_step: StepCallback | None = None,
) -> StructuredTool:
    @boundary(
        "fetch",
        kind="tool",
        extract_input=lambda query: InputState(
            messages=[], graph_state={"name": "fetch", "args": {"query": query}}
        ),
    )
    def fetch_impl(query: str) -> dict:
        result = core.search(query, profile)
        if on_step:
            on_step(
                StepEvent(
                    agent="analyst",
                    action="fetch",
                    detail=result.snippet[:120],
                    query=query,
                    completeness=result.completeness,
                )
            )
        return {
            "query": result.query,
            "snippet": result.snippet,
            "completeness": result.completeness,
        }

    return StructuredTool.from_function(
        fetch_impl,
        name="fetch",
        description="Fetch a topic detail from the research corpus.",
    )

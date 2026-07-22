from __future__ import annotations

from langchain_core.tools import StructuredTool

from examples.agents.research.tools import core
from examples.agents.types import CorpusProfile, StepCallback, StepEvent


def make_search_tool(profile: CorpusProfile, on_step: StepCallback | None = None) -> StructuredTool:
    def invoke(query: str) -> str:
        result = core.search(query, profile)
        if on_step:
            on_step(
                StepEvent(
                    agent="research",
                    action="search",
                    detail=result.snippet[:120],
                    query=query,
                    completeness=result.completeness,
                )
            )
        return result.snippet

    return StructuredTool.from_function(
        invoke,
        name="search",
        description="Search the research corpus for information about a topic.",
    )

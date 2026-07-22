from __future__ import annotations

from examples.agents.protocols import ResearchAgent, SummarizeAgent
from examples.app_config import AgentServerConfig, SummarizeServerConfig


def build_research(config: AgentServerConfig) -> ResearchAgent:
    if config.framework == "langchain":
        from examples.agents.research.langchain.agent import LangChainResearchAgent

        return LangChainResearchAgent(config)
    from examples.agents.research.native.agent import NativeResearchAgent

    return NativeResearchAgent(config)


def build_summarize(config: SummarizeServerConfig) -> SummarizeAgent:
    if config.framework == "langchain":
        from examples.agents.summarize.langchain.agent import LangChainSummarizeAgent

        return LangChainSummarizeAgent(config)
    from examples.agents.summarize.native.agent import NativeSummarizeAgent

    return NativeSummarizeAgent(config)

from __future__ import annotations

from tokenops.agents.protocols import ResearchAgent, SummarizeAgent
from tokenops.config.schema import AgentServerConfig, SummarizeServerConfig


def build_research(config: AgentServerConfig) -> ResearchAgent:
    if config.framework == "langchain":
        from tokenops.agents.research.langchain.agent import LangChainResearchAgent

        return LangChainResearchAgent(config)
    from tokenops.agents.research.native.agent import NativeResearchAgent

    return NativeResearchAgent(config)


def build_summarize(config: SummarizeServerConfig) -> SummarizeAgent:
    if config.framework == "langchain":
        from tokenops.agents.summarize.langchain.agent import LangChainSummarizeAgent

        return LangChainSummarizeAgent(config)
    from tokenops.agents.summarize.native.agent import NativeSummarizeAgent

    return NativeSummarizeAgent(config)

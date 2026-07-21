from __future__ import annotations

from bench.agents.protocols import ResearchAgent, SummarizeAgent
from tokenops.config.schema import AgentServerConfig, SummarizeServerConfig


def build_research(config: AgentServerConfig) -> ResearchAgent:
    if config.framework == "langchain":
        from bench.agents.research.langchain.agent import LangChainResearchAgent

        return LangChainResearchAgent(config)
    from bench.agents.research.native.agent import NativeResearchAgent

    return NativeResearchAgent(config)


def build_summarize(config: SummarizeServerConfig) -> SummarizeAgent:
    if config.framework == "langchain":
        from bench.agents.summarize.langchain.agent import LangChainSummarizeAgent

        return LangChainSummarizeAgent(config)
    from bench.agents.summarize.native.agent import NativeSummarizeAgent

    return NativeSummarizeAgent(config)

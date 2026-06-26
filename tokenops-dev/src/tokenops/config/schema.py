from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tokenops.agents.types import CorpusProfile, Framework


@dataclass
class AgentServerConfig:
    url: str = "http://localhost:8001"
    framework: Framework = "native"
    provider: str = "openai"
    model: str = "gpt-4o-mini"
    port: int = 8001
    max_steps: int = 20
    satisfaction_threshold: float = 0.7
    summarize_url: str = "http://localhost:8002"

    @classmethod
    def from_dict(cls, data: dict[str, Any], defaults: AgentServerConfig | None = None) -> AgentServerConfig:
        base = defaults or cls()
        return cls(
            url=str(data.get("url", base.url)),
            framework=data.get("framework", base.framework),
            provider=str(data.get("provider", base.provider)),
            model=str(data.get("model", base.model)),
            port=int(data.get("port", base.port)),
            max_steps=int(data.get("max_steps", base.max_steps)),
            satisfaction_threshold=float(
                data.get("satisfaction_threshold", base.satisfaction_threshold)
            ),
            summarize_url=str(data.get("summarize_url", base.summarize_url)),
        )


@dataclass
class SummarizeServerConfig:
    url: str = "http://localhost:8002"
    framework: Framework = "native"
    provider: str = "openai"
    model: str = "gpt-4o-mini"
    port: int = 8002

    @classmethod
    def from_dict(cls, data: dict[str, Any], defaults: SummarizeServerConfig | None = None) -> SummarizeServerConfig:
        base = defaults or cls()
        return SummarizeServerConfig(
            url=str(data.get("url", base.url)),
            framework=data.get("framework", base.framework),
            provider=str(data.get("provider", base.provider)),
            model=str(data.get("model", base.model)),
            port=int(data.get("port", base.port)),
        )


@dataclass
class AppConfig:
    task: str = "Research enterprise SaaS pricing"
    corpus_profile: CorpusProfile = "healthy"
    research: AgentServerConfig = field(default_factory=AgentServerConfig)
    summarize: SummarizeServerConfig = field(default_factory=SummarizeServerConfig)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AppConfig:
        agents = data.get("agents", {})
        research_data = agents.get("research", {})
        summarize_data = agents.get("summarize", {})
        return cls(
            task=str(data.get("task", "Research enterprise SaaS pricing")),
            corpus_profile=data.get("corpus_profile", "healthy"),
            research=AgentServerConfig.from_dict(research_data),
            summarize=SummarizeServerConfig.from_dict(summarize_data),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "corpus_profile": self.corpus_profile,
            "agents": {
                "research": {
                    "url": self.research.url,
                    "summarize_url": self.research.summarize_url,
                    "framework": self.research.framework,
                    "provider": self.research.provider,
                    "model": self.research.model,
                    "port": self.research.port,
                    "max_steps": self.research.max_steps,
                    "satisfaction_threshold": self.research.satisfaction_threshold,
                },
                "summarize": {
                    "url": self.summarize.url,
                    "framework": self.summarize.framework,
                    "provider": self.summarize.provider,
                    "model": self.summarize.model,
                    "port": self.summarize.port,
                },
            },
        }

from __future__ import annotations

from typing import Protocol

from examples.agents.types import CorpusProfile, Finding, StepCallback


class ResearchAgent(Protocol):
    def run(
        self,
        task: str,
        corpus_profile: CorpusProfile,
        on_step: StepCallback | None = None,
    ) -> list[Finding]: ...


class SummarizeAgent(Protocol):
    def run(
        self,
        task: str,
        findings: list[Finding],
        on_step: StepCallback | None = None,
    ) -> str: ...

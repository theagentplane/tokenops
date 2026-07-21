from __future__ import annotations

from typing import Any


def agent_card(name: str, description: str, url: str, skills: list[str]) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "url": url,
        "version": "0.1.0",
        "protocol": "a2a-http",
        "skills": [{"id": skill, "name": skill} for skill in skills],
    }


RESEARCH_CARD = lambda url: agent_card(
    name="research-agent",
    description="Researches a topic using search, then delegates to summarizer",
    url=url,
    skills=["research"],
)

SUMMARIZE_CARD = lambda url: agent_card(
    name="summarize-agent",
    description="Summarizes research findings",
    url=url,
    skills=["summarize"],
)

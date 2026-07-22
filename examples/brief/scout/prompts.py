"""Scout prompts — turn a topic into investigation angles + brief sections."""

from __future__ import annotations


def scout_prompt(topic: str, max_angles: int) -> str:
    return f"""You are a market-intel scout. Frame the topic as investigation angles and brief sections.

Topic: {topic}

Respond with JSON only:
{{"angles": ["...", "..."], "sections": ["section 1", "section 2"]}}

Produce at most {max_angles} focused angles. Sections should be 2–4 titles for an exec brief."""

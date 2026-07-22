"""Editor prompts — exec brief from findings + sections."""

from __future__ import annotations

import json


def edit_prompt(
    topic: str,
    findings: list[dict],
    sections: list[str],
    angles: list[str],
) -> str:
    return f"""You are an editor. Produce a short executive market brief.

Topic: {topic}

Sections:
{json.dumps(sections, indent=2)}

Angles investigated:
{json.dumps(angles, indent=2)}

Evidence:
{json.dumps(findings, indent=2)}

Write a concise brief that follows the sections. Plain text only. Keep it under ~250 words."""

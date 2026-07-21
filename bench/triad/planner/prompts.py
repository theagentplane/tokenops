"""Planner prompts — break a user goal into research questions + outline."""

from __future__ import annotations


def plan_prompt(goal: str, max_questions: int) -> str:
    return f"""You are a planning agent. Break the user goal into research questions and a short outline.

Goal: {goal}

Respond with JSON only:
{{"questions": ["...", "..."], "outline": ["section 1", "section 2"]}}

Produce at most {max_questions} focused research questions. Outline should be 2–5 section titles."""

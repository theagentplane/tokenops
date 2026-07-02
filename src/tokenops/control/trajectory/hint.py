"""Format trajectory index rows into an INJECT hint message."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

HintTier = Literal["sequence_only", "sequence_plus_pitfalls", "full"]


@dataclass(frozen=True, kw_only=True)
class TrajectoryHit:
    source_run_id: str
    step_count: int
    cost_micros: int
    tool_sequence: str
    step_summary: str
    match: str  # "exact" | "simhash"


def hint_tier_for(
    index_step_count: int,
    *,
    sequence_only_max_steps: int = 6,
    sequence_plus_pitfalls_max_steps: int = 12,
) -> HintTier:
    """Pick hint depth from indexed trajectory length — longer paths get richer hints."""
    if index_step_count <= sequence_only_max_steps:
        return "sequence_only"
    if index_step_count <= sequence_plus_pitfalls_max_steps:
        return "sequence_plus_pitfalls"
    return "full"


def format_hint(
    entry: TrajectoryHit,
    *,
    tier: HintTier | None = None,
    max_chars: int = 1600,
    sequence_only_max_steps: int = 6,
    sequence_plus_pitfalls_max_steps: int = 12,
) -> str:
    tier = tier or hint_tier_for(
        entry.step_count,
        sequence_only_max_steps=sequence_only_max_steps,
        sequence_plus_pitfalls_max_steps=sequence_plus_pitfalls_max_steps,
    )
    cost_usd = entry.cost_micros / 1_000_000
    header = (
        "[TokenOps trajectory hint — guidance only; verify current state.]\n\n"
        f"Similar completed run ({entry.source_run_id}, {entry.step_count} steps, "
        f"${cost_usd:.2f}, {entry.match} match):\n"
    )
    footer = "\nUse as a starting playbook, not a final answer."

    if tier == "sequence_only":
        body = f"{header}  Path: {entry.tool_sequence}{footer}"
    elif tier == "sequence_plus_pitfalls":
        body = (
            f"{header}  Path: {entry.tool_sequence}\n"
            "  Avoid repeating identical tool args without new information; "
            "follow the sequence order when possible."
            f"{footer}"
        )
    else:
        body = (
            f"{header}  Path: {entry.tool_sequence}\n"
            f"  {entry.step_summary}\n\n"
            "Use as a starting playbook, not a final answer. Avoid repeating identical tool "
            "args without new information."
        )

    if len(body) <= max_chars:
        return body
    return body[: max_chars - 3] + "..."

"""Rewriting the outgoing prompt: steer messages and deep context compaction.

Pure functions over a message list. ``INJECT`` directives are appended as the final user turns
(recency favours the correction over stale task history), and ``context_compaction`` pins every
system message and drops duplicate non-system ones.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from tokenops.framework.engine import ApplyControls

__all__ = ["apply_carry_to_messages", "compact_messages", "consume_carry", "estimate_input_tokens"]


def estimate_input_tokens(messages: object) -> int:
    """Rough prompt size: four characters to a token, never below one."""
    return max(1, len(str(messages)) // 4)


def apply_carry_to_messages(
    messages: Sequence[Any],
    carry: Sequence[str],
    *,
    as_user: Callable[[str], object] | None = None,
) -> list[Any]:
    """Append governance INJECT directives as the final user turns.

    Steer messages belong at the end of the context so recency favors the correction
    over stale task history, not as a prepended system slot."""
    out = list(messages)
    for text in carry:
        out.append(as_user(text) if as_user is not None else {"role": "user", "content": text})
    return out


def consume_carry(
    controls: ApplyControls,
    messages: Sequence[Any],
    *,
    as_user: Callable[[str], object] | None = None,
) -> list[Any]:
    """Apply pending ``controls.carry`` injects and clear the queue."""
    out = apply_carry_to_messages(messages, controls.carry, as_user=as_user)
    controls.carry.clear()
    return out


def compact_messages(
    messages: Sequence[Any],
    *,
    estimate: Callable[[object], int] | None = None,
) -> tuple[list[Any], dict[str, int]]:
    """Deep ``context_compaction`` MUTATE: rewrite the outgoing messages.

    Pins every system message and drops duplicate non-system messages (deduped tool outputs
    and repeated context). Returns ``(compacted_messages, metadata)`` where *metadata* holds
    ``tokens_before``, ``tokens_after`` and ``tokens_saved`` (ints, at least 0). If *estimate*
    is ``None`` the counts are 0 (the caller opts out of measurement).
    """
    seen: set[tuple[str | None, str]] = set()
    out: list[Any] = []
    for msg in messages:
        role = msg.get("role") if isinstance(msg, dict) else None
        content = msg.get("content", "") if isinstance(msg, dict) else str(msg)
        if role == "system":
            out.append(msg)
            continue
        if isinstance(content, str) and content.startswith("[TokenOps trajectory hint"):
            out.append(msg)
            continue
        key = (role, content)
        if key in seen:
            continue
        seen.add(key)
        out.append(msg)
    if estimate is None:
        return out, {"tokens_before": 0, "tokens_after": 0, "tokens_saved": 0}
    before = estimate(messages)
    after = estimate(out)
    return out, {
        "tokens_before": before,
        "tokens_after": after,
        "tokens_saved": max(0, before - after),
    }

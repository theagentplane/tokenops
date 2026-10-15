"""Small helpers shared by the two ways an observation is built (crossings and agent steps)."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from tokenops.framework.context import current_span

__all__ = ["short_hash", "span_fields", "tool_signature"]


def tool_signature(name: str, args: object) -> str:
    """Stable short hash of a tool name and its arguments."""
    payload = json.dumps([name, args], sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def short_hash(text: object) -> str:
    """Stable short hash of any value's string form."""
    return hashlib.sha256(str(text).encode()).hexdigest()[:16]


def span_fields(service: str = "") -> dict[str, Any]:
    """``service`` / ``span_id`` / ``parent_span_id`` of the current span, or blanks."""
    span = current_span()
    if span is None:
        return {"service": service, "span_id": "", "parent_span_id": None}
    return {
        "service": span.service or service,
        "span_id": span.span_id,
        "parent_span_id": span.parent_span_id,
    }

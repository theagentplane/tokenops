"""HTTP propagation helpers — inject TokenOps run/span headers from ambient context.

Agent code should not manually thread ``X-TokenOps-Run-Id``. Instrumented HTTP
clients call :func:`merge_propagation_headers` so outbound calls carry the
current run and treat the current span as the parent of the next hop (natural
span bifurcation across agents).
"""

from __future__ import annotations

from typing import Mapping

from tokenops.control.context import (
    PARENT_SPAN_ID_HEADER,
    RUN_ID_HEADER,
    current_registration,
    current_span,
)


def propagation_headers() -> dict[str, str]:
    """Headers derived from ambient registration + span (may be empty)."""
    out: dict[str, str] = {}
    reg = current_registration()
    if reg is not None and reg.run_id:
        out[RUN_ID_HEADER] = reg.run_id
    span = current_span()
    if span is not None and span.span_id:
        # Downstream agent opens a *new* span with this as parent.
        out[PARENT_SPAN_ID_HEADER] = span.span_id
    return out


def merge_propagation_headers(
    headers: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Merge explicit headers over ambient propagation (explicit wins)."""
    merged = dict(propagation_headers())
    if headers:
        for key, value in headers.items():
            if value is None:
                continue
            text = str(value).strip()
            if text:
                merged[key] = text
    return merged

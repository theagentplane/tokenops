"""The Chronicle span a TokenOps run executes in.

A run is a Chronicle trace: its only identifier is ``trace_id``. A hop arrives with the
caller's ``traceparent`` and joins that trace; the entry hop starts a new one. This module is
the single place that reads the active Chronicle span, so the rest of TokenOps
never touches Chronicle's session.

``chronicle.current_session`` (Chronicle 1.1) reads the active session without opening one;
``chronicle.span`` opens one from inbound headers when none is active.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass

import chronicle


@dataclass(frozen=True)
class TraceSpan:
    """Identity of the Chronicle span for this hop."""

    trace_id: str
    span_id: str
    parent_id: str | None


@contextmanager
def chronicle_span(headers: Mapping[str, str] | None, *, service: str) -> Iterator[TraceSpan]:
    """Yield the active Chronicle span, opening one (from ``headers``) when none is active."""
    active = chronicle.current_session()
    if active is not None:
        yield TraceSpan(active.trace_id, active.span_id, active.parent_envelope_id)
        return
    with chronicle.span(dict(headers) if headers else None, service=service) as session:
        yield TraceSpan(session.trace_id, session.span_id, session.parent_envelope_id)

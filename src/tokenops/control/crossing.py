"""Chronicle boundary hook -> TokenOps govern (pre_call + observe).

One Chronicle ``Hook`` (registered on ``chronicle.default_hooks``) handles the three events
TokenOps cares about for ``@boundary`` / ``wrap_llm`` crossings:

* ``enter``: before the wrapped call (LLM pre_call; may patch kwargs or stop the call)
* ``crossing``: the call returned and was captured (observe)
* ``leave``: after the attempt, when ``enter`` completed (ledger complete)

Stopping a call is done by raising an exception that Chronicle propagates: ``Halt`` is a
``BaseException`` and ``Throttled`` is an ``AbortCall``, so neither is swallowed by the hook
failure policy.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

from chronicle import CallInfo, Hook, default_hooks

# When wrap_complete / wrap_stream already run pre_call + admit, skip boundary pre_call
# so LLM calls are not governed twice.
_wrap_owns_precall: ContextVar[bool] = ContextVar("tokenops_wrap_owns_precall", default=False)
_inflight_seg: ContextVar[str | None] = ContextVar("tokenops_inflight_seg", default=None)


def wrap_owns_precall(active: bool) -> Any:
    """Context manager token: ``wrap_complete`` sets True while it owns pre_call."""
    return _wrap_owns_precall.set(active)


def reset_wrap_owns_precall(token: Any) -> None:
    _wrap_owns_precall.reset(token)


def _service_name() -> str:
    from tokenops.control.context import current_span

    span = current_span()
    return span.service if span else "unknown"


def _kind(call: CallInfo) -> str:
    return str(getattr(call.kind, "value", call.kind))


def _estimate_input_tokens(state: dict[str, object]) -> int:
    messages = state.get("messages")
    if messages is None:
        messages = state
    return max(1, len(str(messages)) // 4)


def on_enter(info: CallInfo) -> dict[str, Any] | None:
    """LLM-kind pre_call: may Halt, or return kwargs patches (max_output / model)."""
    if _kind(info) != "llm" or _wrap_owns_precall.get():
        return None

    from tokenops.control.context import current_governance, current_registration
    from tokenops.control.core import CallRequest

    gov_ctx = current_governance()
    if gov_ctx is None or current_registration() is None:
        return None

    governor = gov_ctx.governor
    controls = governor.controls
    begin = getattr(controls, "begin_call", None)
    if callable(begin):
        begin()

    state: dict[str, object] = dict(info.arguments)
    provider = str(state.get("provider") or gov_ctx.provider or "")
    model = str(state.get("model") or gov_ctx.model or "")
    raw_cap = state.get("max_output_tokens")
    max_out: int | None = None
    if isinstance(raw_cap, bool):
        max_out = None
    elif isinstance(raw_cap, int):
        max_out = raw_cap
    elif isinstance(raw_cap, str):
        try:
            max_out = int(raw_cap)
        except ValueError:
            max_out = None

    request = CallRequest(
        attr=gov_ctx.attr,
        provider=provider,
        model=model,
        estimated_input_tokens=_estimate_input_tokens(state),
        max_output_tokens=max_out,
    )
    governor.pre_call(request)

    seg = f"run:{gov_ctx.attr.run_id}"
    governor.ledger.admit(seg)
    _inflight_seg.set(seg)

    patch: dict[str, Any] = {}
    call = getattr(controls, "call", None)
    if call is not None:
        if getattr(call, "max_output_tokens", None) is not None:
            patch["max_output_tokens"] = call.max_output_tokens
        if getattr(call, "model_override", None):
            patch["model"] = call.model_override
    return patch or None


def on_leave(info: CallInfo) -> None:
    """Release inflight admit from :func:`on_enter` (success or failure)."""
    del info
    from tokenops.control.context import current_governance

    seg = _inflight_seg.get()
    if not seg:
        return
    gov_ctx = current_governance()
    try:
        if gov_ctx is not None:
            gov_ctx.governor.ledger.complete(seg)
    finally:
        _inflight_seg.set(None)


def on_crossing(info: CallInfo, result: Any) -> None:
    """Project crossing → Observation when registration + governance are bound."""
    from tokenops.control.boundary import emit_observation, observation_from_crossing
    from tokenops.control.context import current_governance, current_registration

    if current_governance() is None or current_registration() is None:
        return
    gov = current_governance()
    state: dict[str, object] = dict(info.arguments)
    # Prefer provider/model from the crossing (e.g. wrap_llm dispatch args) so
    # MUTATE model overrides price correctly; fall back to bound governance.
    provider = str(state.get("provider") or (gov.provider if gov else "") or "")
    model = str(state.get("model") or (gov.model if gov else "") or "")
    # Compaction metadata: carried from _compact_messages via controls.call
    compaction = None
    governor = getattr(gov, "governor", None)
    controls = getattr(governor, "controls", None)
    if controls is not None:
        call = getattr(controls, "call", None)
        comp = getattr(call, "compaction", None) if call is not None else None
        if comp is not None:
            compaction = dict(comp)
    obs = observation_from_crossing(
        boundary_id=info.name,
        kind=_kind(info),
        service=_service_name(),
        input_state=state,
        result=result,
        provider=provider,
        model=model,
        compaction=compaction,
    )
    emit_observation(obs)


class TokenOpsHook(Hook):
    """The Chronicle hook that drives the governor from boundary crossings."""

    def enter(self, call: CallInfo) -> dict[str, Any] | None:
        return on_enter(call)

    def leave(self, call: CallInfo) -> None:
        on_leave(call)

    def crossing(self, call: CallInfo, result: Any) -> None:
        on_crossing(call, result)


_hook = TokenOpsHook()


def install_crossing_hook() -> None:
    """Register the TokenOps hook on ``chronicle.default_hooks`` (idempotent).

    Default hooks are inherited by every Chronicle session, so nothing needs re-attaching
    after a session is created.
    """
    if _hook not in list(default_hooks):
        default_hooks.register(_hook)

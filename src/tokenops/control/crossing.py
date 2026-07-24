"""Chronicle boundary hooks → TokenOps govern (pre_call + observe).

Chronicle ``@boundary`` / ``wrap_llm`` invoke:

* ``session.on_enter`` after input capture, before the wrapped call (LLM pre_call)
* ``session.on_crossing`` after LIVE record / cut-point (observe)
* ``session.on_leave`` after the attempt when ``on_enter`` completed (ledger complete)

``reset_session()`` clears hooks, so ``install_crossing_hook`` wraps ``reset_session``
to re-attach all three.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

from chronicle.envelope.schema import Envelope, InputState
from chronicle.session import ChronicleSession, get_session

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


def _input_state_to_dict(input_state: InputState) -> dict[str, object]:
    d: dict[str, object] = dict(input_state.graph_state)
    if input_state.messages:
        d["messages"] = input_state.messages
    if input_state.system_prompt:
        d["system_prompt"] = input_state.system_prompt
    return d


def _estimate_input_tokens(state: dict[str, object]) -> int:
    messages = state.get("messages")
    if messages is None:
        messages = state
    return max(1, len(str(messages)) // 4)


def on_enter(
    boundary_id: str,
    kind: str,
    input_state: InputState,
) -> dict[str, Any] | None:
    """LLM-kind pre_call: may Halt, or return kwargs patches (max_output / model)."""
    del boundary_id  # used for tracing only; attribution comes from run scope
    if kind != "llm" or _wrap_owns_precall.get():
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

    state = _input_state_to_dict(input_state)
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


def on_leave(boundary_id: str, kind: str, input_state: InputState) -> None:
    """Release inflight admit from :func:`on_enter` (success or failure)."""
    del boundary_id, kind, input_state
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


def on_crossing(
    boundary_id: str,
    kind: str,
    input_state: InputState,
    result: Any,
) -> None:
    """Project crossing → Observation when registration + governance are bound."""
    from tokenops.control.boundary import emit_observation, observation_from_crossing
    from tokenops.control.context import current_governance, current_registration

    if current_governance() is None or current_registration() is None:
        return
    gov = current_governance()
    state = _input_state_to_dict(input_state)
    # Prefer provider/model from the crossing (e.g. wrap_llm dispatch args) so
    # MUTATE model overrides price correctly; fall back to bound governance.
    provider = str(state.get("provider") or (gov.provider if gov else "") or "")
    model = str(state.get("model") or (gov.model if gov else "") or "")
    obs = observation_from_crossing(
        boundary_id=boundary_id,
        kind=kind,
        service=_service_name(),
        input_state=state,
        result=result,
        provider=provider,
        model=model,
    )
    emit_observation(obs)


def _ensure_recorded_envelopes_alias() -> None:
    """Expose read-only ``recorded_envelopes`` (upstream keeps a private list)."""
    if hasattr(ChronicleSession, "recorded_envelopes"):
        return

    @property  # type: ignore[misc]
    def recorded_envelopes(self) -> list[Envelope]:
        return list(self._recorded_envelopes)

    ChronicleSession.recorded_envelopes = recorded_envelopes  # type: ignore[attr-defined]


def _attach(session: ChronicleSession) -> ChronicleSession:
    session.on_crossing = on_crossing
    session.on_enter = on_enter
    session.on_leave = on_leave
    return session


def install_crossing_hook() -> None:
    """Attach enter/crossing/leave hooks to the current session and every ``reset_session()``.

    Idempotent. Patches ``chronicle.session.reset_session`` (and rebinds the
    ``chronicle`` package export when present) so callers keep the wrapped entrypoint.
    Prefer ``chronicle.session.reset_session`` (attribute access) over
    ``from chronicle import reset_session`` so you always see the live hook.
    """
    import chronicle as chronicle_pkg
    import chronicle.session as session_mod

    _ensure_recorded_envelopes_alias()
    _attach(get_session())

    current = session_mod.reset_session
    if getattr(current, "_tokenops_crossing_hook", False):
        return

    original = current

    def reset_session_with_hook() -> ChronicleSession:
        return _attach(original())

    reset_session_with_hook._tokenops_crossing_hook = True  # type: ignore[attr-defined]
    session_mod.reset_session = reset_session_with_hook
    chronicle_pkg.reset_session = reset_session_with_hook

"""Chronicle ``on_crossing`` → TokenOps govern ingest.

Chronicle's ``@boundary`` invokes ``session.on_crossing`` after LIVE record and
LIVE cut-point. ``reset_session()`` creates a fresh session with ``on_crossing``
cleared, so ``install_crossing_hook`` wraps ``reset_session`` to re-attach.
"""

from __future__ import annotations

from typing import Any

from chronicle.envelope.schema import Envelope, InputState
from chronicle.session import ChronicleSession, get_session


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
    obs = observation_from_crossing(
        boundary_id=boundary_id,
        kind=kind,
        service=_service_name(),
        input_state=_input_state_to_dict(input_state),
        result=result,
        provider=gov.provider if gov else "",
        model=gov.model if gov else "",
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
    return session


def install_crossing_hook() -> None:
    """Attach ``on_crossing`` to the current session and every ``reset_session()``.

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

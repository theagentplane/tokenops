"""Chronicle runtime session: record, replay, and cut-point execution."""

from __future__ import annotations

import os
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from tokenops.chronicle.replay import ReplayPlan
from tokenops.chronicle.schema import ActionResult, InputState, ToolCall

_envelope_stack: ContextVar[list[str]] = ContextVar("chronicle_envelope_stack", default=[])


class SessionMode(str, Enum):
    LIVE = "live"
    REPLAY = "replay"


@dataclass
class RecordedEnvelope:
    """In-memory envelope — Chronicle ``Envelope`` projection for v1."""

    envelope_id: str
    trace_id: str
    node_id: str
    boundary_kind: str
    parent_envelope_id: str | None
    sequence: int
    invocation_index: int
    input_state: InputState
    action_result: ActionResult


@dataclass
class CallRecord:
    boundary_id: str
    invocation_index: int
    mode: str
    envelope_id: str | None = None


@dataclass
class ChronicleSession:
    mode: SessionMode = SessionMode.LIVE
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    replay_plan: ReplayPlan = field(default_factory=ReplayPlan)
    model_version: str = "demo-model"
    build_id: str = field(default_factory=lambda: os.environ.get("CHRONICLE_BUILD_ID", "dev-local"))

    _sequence: int = 0
    _invocation_counts: dict[str, int] = field(default_factory=dict)
    _replay_cursor: dict[str, int] = field(default_factory=dict)
    _call_log: list[CallRecord] = field(default_factory=list)
    _captured_inputs: dict[tuple[str, int], InputState] = field(default_factory=dict)
    _captured_results: dict[tuple[str, int], Any] = field(default_factory=dict)
    _recorded_envelopes: list[RecordedEnvelope] = field(default_factory=list)
    _fixture_returns: dict[tuple[str, int], Any] = field(default_factory=dict)
    _last_envelope_id: str | None = None

    def begin_trace(self, trace_id: str | None = None) -> str:
        if trace_id:
            self.trace_id = trace_id
        else:
            self.trace_id = str(uuid.uuid4())
        self._sequence = 0
        self._invocation_counts.clear()
        self._replay_cursor.clear()
        self._call_log.clear()
        self._captured_inputs.clear()
        self._captured_results.clear()
        self._recorded_envelopes.clear()
        self._last_envelope_id = None
        _envelope_stack.set([])
        return self.trace_id

    def enable_replay(self, plan: ReplayPlan | None = None) -> None:
        self.mode = SessionMode.REPLAY
        self.replay_plan = plan or ReplayPlan()
        self._replay_cursor.clear()

    def enable_live(self) -> None:
        self.mode = SessionMode.LIVE
        self._fixture_returns.clear()

    def load_fixture_returns(self, mapping: dict[tuple[str, int], Any]) -> None:
        """Load stub return values keyed by ``(boundary_id, invocation_index)``."""
        self._fixture_returns = dict(mapping)

    def current_parent_id(self) -> str | None:
        stack = _envelope_stack.get()
        return stack[-1] if stack else None

    def _push_envelope(self, envelope_id: str) -> None:
        stack = _envelope_stack.get().copy()
        stack.append(envelope_id)
        _envelope_stack.set(stack)

    def _pop_envelope(self) -> None:
        stack = _envelope_stack.get().copy()
        if stack:
            stack.pop()
        _envelope_stack.set(stack)

    def next_invocation(self, boundary_id: str) -> int:
        count = self._invocation_counts.get(boundary_id, 0) + 1
        self._invocation_counts[boundary_id] = count
        return count

    def next_sequence(self) -> int:
        self._sequence += 1
        return self._sequence

    def record_envelope(
        self,
        boundary_id: str,
        kind: str,
        input_state: InputState,
        action_result: ActionResult,
    ) -> RecordedEnvelope:
        invocation_index = self.next_invocation(boundary_id)
        sequence = self.next_sequence()
        parent_id = self._last_envelope_id
        envelope_id = str(uuid.uuid4())

        envelope = RecordedEnvelope(
            envelope_id=envelope_id,
            trace_id=self.trace_id,
            node_id=boundary_id,
            boundary_kind=kind,
            parent_envelope_id=parent_id,
            sequence=sequence,
            invocation_index=invocation_index,
            input_state=input_state,
            action_result=action_result,
        )

        self._push_envelope(envelope_id)
        try:
            self._recorded_envelopes.append(envelope)
            self._last_envelope_id = envelope_id
        finally:
            self._pop_envelope()

        self._call_log.append(
            CallRecord(boundary_id, invocation_index, "record", envelope.envelope_id)
        )
        return envelope

    def _fixture_for(self, boundary_id: str) -> Any:
        cursor = self._replay_cursor.get(boundary_id, 0) + 1
        self._replay_cursor[boundary_id] = cursor
        key = (boundary_id, cursor)
        if key not in self._fixture_returns:
            raise RuntimeError(
                f"No fixture for {boundary_id!r} invocation {cursor} — "
                "load_fixture_returns() or load_trace() first"
            )
        self._call_log.append(CallRecord(boundary_id, cursor, "stub", None))
        return self._fixture_returns[key]

    def stub_result(self, boundary_id: str, kind: str) -> Any:
        return self._fixture_for(boundary_id)

    def capture_live_input(self, boundary_id: str, invocation_index: int, input_state: InputState) -> None:
        self._captured_inputs[(boundary_id, invocation_index)] = input_state

    def capture_live_result(self, boundary_id: str, invocation_index: int, result: Any) -> None:
        self._captured_results[(boundary_id, invocation_index)] = result
        self._call_log.append(CallRecord(boundary_id, invocation_index, "live", None))

    def captured_input(self, boundary_id: str, invocation_index: int) -> InputState | None:
        return self._captured_inputs.get((boundary_id, invocation_index))

    def captured_result(self, boundary_id: str, invocation_index: int) -> Any:
        return self._captured_results.get((boundary_id, invocation_index))

    def invocation_count(self, boundary_id: str) -> int:
        return sum(1 for c in self._call_log if c.boundary_id == boundary_id)

    def call_log(self) -> list[CallRecord]:
        return list(self._call_log)

    @property
    def recorded_envelopes(self) -> list[RecordedEnvelope]:
        return list(self._recorded_envelopes)


_session: ChronicleSession | None = None


def get_session() -> ChronicleSession:
    global _session
    if _session is None:
        _session = ChronicleSession()
    return _session


def reset_session() -> ChronicleSession:
    global _session
    _session = ChronicleSession()
    return _session


def result_to_action_result(result: Any, kind: str) -> ActionResult:
    if kind == "tool" and isinstance(result, dict):
        return ActionResult(completion=result.get("status", str(result)), raw_response=result)
    if kind == "llm" and isinstance(result, dict):
        tool_calls = [
            ToolCall(
                id=tc.get("id"),
                name=tc.get("name", ""),
                arguments=tc.get("arguments", {}),
            )
            for tc in result.get("tool_calls", [])
        ]
        return ActionResult(
            tool_calls=tool_calls,
            completion=result.get("completion"),
            finish_reason=result.get("finish_reason"),
        )
    if hasattr(result, "content"):
        return ActionResult(
            completion=str(getattr(result, "content", "")),
            raw_response={
                "input_tokens": getattr(result, "input_tokens", 0),
                "output_tokens": getattr(result, "output_tokens", 0),
            },
        )
    if hasattr(result, "snippet"):
        return ActionResult(
            completion=getattr(result, "snippet", str(result))[:200],
            raw_response=result,
        )
    return ActionResult(completion=str(result), raw_response=result if isinstance(result, dict) else None)


def envelope_to_return_value(envelope: RecordedEnvelope, kind: str) -> Any:
    if kind == "tool":
        raw = envelope.action_result.raw_response
        if raw is not None:
            return raw
        return {"status": envelope.action_result.completion or "ok"}
    if kind == "llm" and isinstance(envelope.action_result.raw_response, dict):
        return envelope.action_result.raw_response
    raw = envelope.action_result.raw_response
    if raw is not None:
        return raw
    return envelope.action_result.completion

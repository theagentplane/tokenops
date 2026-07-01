"""Replay plan: stub vs live per boundary invocation (Chronicle-compatible)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class BoundaryMode(str, Enum):
    STUB = "stub"
    LIVE = "live"


@dataclass
class ReplayPlan:
    """Controls which annotated boundaries stub from fixtures vs run live code."""

    default: BoundaryMode = BoundaryMode.STUB
    _overrides: dict[tuple[str, int | None], BoundaryMode] = field(default_factory=dict)

    def stub(self, boundary_id: str, invocation: int | None = None) -> ReplayPlan:
        self._overrides[(boundary_id, invocation)] = BoundaryMode.STUB
        if invocation is None:
            self._overrides[(boundary_id, None)] = BoundaryMode.STUB
        return self

    def live(self, boundary_id: str, invocation: int | None = None) -> ReplayPlan:
        self._overrides[(boundary_id, invocation)] = BoundaryMode.LIVE
        if invocation is None:
            self._overrides[(boundary_id, None)] = BoundaryMode.LIVE
        return self

    def stub_all(self) -> ReplayPlan:
        self.default = BoundaryMode.STUB
        return self

    def mode_for(self, boundary_id: str, invocation_index: int) -> BoundaryMode:
        specific = self._overrides.get((boundary_id, invocation_index))
        if specific is not None:
            return specific
        general = self._overrides.get((boundary_id, None))
        if general is not None:
            return general
        return self.default

    def should_stub(self, boundary_id: str, invocation_index: int) -> bool:
        return self.mode_for(boundary_id, invocation_index) == BoundaryMode.STUB

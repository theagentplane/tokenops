"""Shared types for live benchmarks."""

from __future__ import annotations

import enum
from dataclasses import dataclass

DEFAULT_LIMIT_MICROS = 1_000_000


class BenchmarkMode(str, enum.Enum):
    CIRCUIT_BREAKER = "circuit_breaker"
    TOKENOPS = "tokenops"


class CompareMode(str, enum.Enum):
    UNGOVERNED = "ungoverned"
    TOKENOPS = "tokenops"


@dataclass
class RunOutcome:
    scenario_id: str
    success: bool
    spend_micros: int
    steps: int
    halt_reason: str | None = None

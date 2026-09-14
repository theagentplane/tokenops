from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ModelResponse:
    """Inclusive input/output totals; cached/reasoning are subsets, not extra tokens."""

    content: str
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    reasoning_tokens: int = 0

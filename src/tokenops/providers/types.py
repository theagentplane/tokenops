from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ModelResponse:
    content: str
    input_tokens: int = 0
    output_tokens: int = 0

"""Types for tool-output pruning: a span of hideable text and the interface a language handler implements."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True)
class Span:
    """A comment or docstring in a text. Rows are 1-based, `col` is where a comment starts on its first row."""

    kind: Literal["comment", "docstring"]
    first_row: int
    last_row: int
    col: int = 0
    text: str = ""


class LanguageHandler(Protocol):
    """Finds the hideable spans of one language. The shared driver does everything else."""

    name: str
    min_score: float  # `score` must reach this for the driver to act
    hidden_doc: str  # what a hidden docstring or doc comment is replaced with on its first line

    def score(self, text: str) -> float:
        """How strongly `text` has this language's structure; 0 when it does not."""
        ...

    def spans(self, text: str) -> list[Span] | None:
        """Comment and docstring spans, or None to refuse (the text does not lex cleanly)."""
        ...

    def keep(self, span: Span) -> bool:
        """True for a span that must stay visible (a comment a tool reads, a pragma)."""
        ...

    def same_code(self, before: str, after: str) -> bool:
        """The safety contract: the code is identical before and after, comments and docstrings aside."""
        ...

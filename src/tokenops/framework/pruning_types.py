"""Types for tool-output pruning: a span of hideable text and the interface a language handler implements."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True)
class Span:
    """A comment or docstring in a text. Rows are 1-based.

    `col` is where a comment starts on its first row; `end_col` is where it ends on its last row (-1: at the end of
    the line, which is the case for every line comment). `significant` marks a span the handler knows must stay
    (for example a Go cgo preamble), whatever its text says."""

    kind: Literal["comment", "docstring"]
    first_row: int
    last_row: int
    col: int = 0
    text: str = ""
    end_col: int = -1
    significant: bool = False


class LanguageHandler(Protocol):
    """Finds the hideable spans of one language. The shared driver does everything else."""

    name: str
    min_score: float  # `score` must reach this for the driver to act
    hidden_doc: str  # what a hidden docstring or doc comment is replaced with on its first line

    def score(self, text: str) -> float:
        """How strongly `text` has this language's structure; 0 when it does not."""

    def spans(self, text: str) -> list[Span] | None:
        """Comment and docstring spans, or None to refuse (the text does not lex cleanly)."""

    def keep(self, span: Span) -> bool:
        """True for a span that must stay visible (a comment a tool reads, a pragma)."""

    def same_code(self, before: str, after: str) -> bool:
        """The safety contract: the code is identical before and after, comments and docstrings aside."""


@dataclass(frozen=True)
class CLexConfig:
    """How a C-style language differs for the shared lexer (see ``pruning_clex``)."""

    nested_comments: bool = False  # Rust: /* /* */ */
    line_continuation: bool = False  # C/C++: a backslash at the end of a // comment continues it
    multiline_strings: bool = False  # Rust: "..." may span lines
    go_raw_strings: bool = False  # Go: `...`
    rust_raw_strings: bool = False  # Rust: r"..." r#"..."# br"..."
    cpp_raw_strings: bool = False  # C++: R"delim(...)delim"
    text_blocks: bool = False  # Java: """..."""
    rust_chars: bool = False  # Rust: 'a is a lifetime, 'a' is a char
    digit_separators: bool = False  # C++14: 1'000'000


@dataclass(frozen=True)
class CComment:
    """A comment found by the lexer: character offsets into the text, end exclusive."""

    start: int
    end: int
    block: bool


@dataclass(frozen=True)
class CLexed:
    """Result of lexing C-style source: its comments, and the code with comments and whitespace removed.

    `skeleton` is the safety contract: every run of whitespace and comments collapses to one space and strings are
    kept verbatim, so two texts with the same skeleton have the same code."""

    comments: list[CComment]
    skeleton: str

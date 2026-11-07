"""Hide comments and docstrings in a tool result that is source code, from the result text alone.

The pruner does not know the command that produced the text, and the text may be a fragment (a ``sed`` range can start or
end inside a docstring, mid-block, or mid-statement). So it only acts when a language handler can show the text is that
language's source, and it only hides what the handler can prove is a comment or docstring. When in doubt it returns
``None`` and the result goes through untouched. It never changes a code line, and it keeps the number of lines the same
(a hidden block becomes blank lines), so line numbers the agent has seen or will cite still hold.

This module is the shared driver: the detection exclusions (diffs, ``grep -n`` hits, numbered listings, test reports),
the line-count-preserving rewrite, the note, the minimum-saving rule and the safety contract. A ``LanguageHandler``
(see ``pruning_types``) only finds the spans. Pure, model-free and dependency-free.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from tokenops.framework.pruning_python import HIDDEN_DOCSTRING, PythonHandler
from tokenops.framework.pruning_types import LanguageHandler, Span

__all__ = [
    "HIDDEN_DOCSTRING",
    "NOTE",
    "looks_like_python_source",
    "prune",
    "prune_any",
    "select_handler",
    "prune_python",
]

NOTE = (
    "[TokenOps: comments and docstrings are hidden in this output; line numbers are unchanged. "
    "`grep -n` shows a specific comment or docstring line.]"
)

# Output that merely contains code lines: diffs, grep -n hits, test reports. Never pruned.
_NOT_SOURCE = re.compile(
    r"^(diff --git |@@ |\+\+\+ |--- [ab]/|={3,} \S.* ={3,}$|E {3}|[\w./\\-]+:\d+:)", re.M
)
_NUMBERED = re.compile(
    r"^\s*\d+[\t:|]\s", re.M
)  # cat -n / nl listings: most lines start with a number
MIN_LINES = 8

_PYTHON = PythonHandler()


def _passes_exclusions(text: str) -> bool:
    """False for an output that merely contains code lines (a diff, grep hits, a numbered listing, a test report)."""
    lines = [ln for ln in text.split("\n") if ln.strip()]
    if len(lines) < MIN_LINES or _NOT_SOURCE.search(text):
        return False
    return len(_NUMBERED.findall(text)) <= 0.4 * len(lines)


def _is_source_of(text: str, handler: LanguageHandler) -> bool:
    """True when `text` is a block of `handler`'s language, not an output that merely contains some code."""
    return _passes_exclusions(text) and handler.score(text) >= handler.min_score


def looks_like_python_source(text: str) -> bool:
    """True when `text` is a block of Python source, not an output that merely contains some code."""
    return _is_source_of(text, _PYTHON)


def select_handler(text: str, handlers: Sequence[LanguageHandler]) -> LanguageHandler | None:
    """The handler whose language `text` is, or None when none is clearly it.

    One enabled handler needs no comparison. With several, the best score must reach its minimum and clearly beat the
    runner-up (at least 1.5 times and 2 more); two close scores mean the language is ambiguous, so nothing is pruned."""
    if len(handlers) == 1:
        return handlers[0]
    ranked = sorted(
        ((h.score(text), i, h) for i, h in enumerate(handlers)), key=lambda t: (-t[0], t[1])
    )
    if not ranked or ranked[0][0] < ranked[0][2].min_score:
        return None
    top = ranked[0][0]
    second = ranked[1][0]
    if second and (top < 1.5 * second or top - second < 2):
        return None
    return ranked[0][2]


def _position(span: Span) -> tuple[int, int]:
    return span.first_row, span.col


def _hide_comment(lines: list[str], s: Span) -> None:
    """Blank or trim the comment `s` in `lines`, keeping every code character and the number of lines."""
    first = lines[s.first_row - 1]
    before = first[: s.col]
    if s.first_row == s.last_row:
        after = first[s.end_col :] if s.end_col >= 0 else ""
        if not after.strip():
            lines[s.first_row - 1] = before.rstrip() if before.strip() else ""
        elif not before.strip():
            lines[s.first_row - 1] = before + after.lstrip()
        else:
            lines[s.first_row - 1] = before.rstrip() + " " + after.lstrip()
        return
    lines[s.first_row - 1] = before.rstrip() if before.strip() else ""
    for i in range(s.first_row, s.last_row - 1):
        lines[i] = ""
    last = lines[s.last_row - 1]
    after = last[s.end_col :] if s.end_col >= 0 else ""
    lines[s.last_row - 1] = after.lstrip() if after.strip() else ""


def prune(
    text: str,
    handler: LanguageHandler,
    *,
    comments: bool = True,
    docstrings: bool = True,
    min_saved_chars: int = 200,
) -> str | None:
    """`text` with comments and/or docstrings hidden and the same number of lines, or None to leave it as it is.

    None when: it is not `handler`'s source, the handler refuses it, it would save fewer than `min_saved_chars` (after
    the note), or the handler says the code would differ."""
    if not (comments or docstrings) or not _is_source_of(text, handler):
        return None
    found = handler.spans(text)
    if found is None:
        return None
    original = text.split("\n")
    lines = list(original)
    n = len(lines)
    wanted = [
        s
        for s in found
        if (comments if s.kind == "comment" else docstrings) and not handler.keep(s)
    ]

    # Right to left, so that editing a comment never moves the column of one before it on the same line.
    for s in sorted((s for s in wanted if s.kind == "comment"), key=_position, reverse=True):
        if s.last_row <= n:
            _hide_comment(lines, s)
    for s in wanted:
        if s.kind == "docstring" and s.last_row <= n:
            first = original[s.first_row - 1]
            indent = first[: len(first) - len(first.lstrip(" \t"))]
            lines[s.first_row - 1] = indent + handler.hidden_doc
            for i in range(s.first_row, s.last_row):
                lines[i] = ""

    out = "\n".join(lines)
    if len(text) - len(out) - len(NOTE) - 1 < min_saved_chars:
        return None
    if not handler.same_code(text, out):
        return None
    # Never strip trailing blank lines: a hidden last comment leaves some, and the line count must not change.
    if text.endswith("\n"):
        return out + NOTE + "\n"
    return out + "\n" + NOTE


def prune_any(
    text: str,
    handlers: Sequence[LanguageHandler],
    *,
    comments: bool = True,
    docstrings: bool = True,
    min_saved_chars: int = 200,
) -> str | None:
    """`prune` with the handler that `select_handler` picks for `text` among `handlers`."""
    if not handlers or not (comments or docstrings) or not _passes_exclusions(text):
        return None
    handler = select_handler(text, handlers)
    if handler is None:
        return None
    return prune(
        text, handler, comments=comments, docstrings=docstrings, min_saved_chars=min_saved_chars
    )


def prune_python(
    text: str, *, comments: bool = True, docstrings: bool = True, min_saved_chars: int = 200
) -> str | None:
    """`prune` with the Python handler."""
    return prune(
        text, _PYTHON, comments=comments, docstrings=docstrings, min_saved_chars=min_saved_chars
    )

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

from tokenops.framework.pruning_python import HIDDEN_DOCSTRING, PythonHandler
from tokenops.framework.pruning_types import LanguageHandler, Span

__all__ = [
    "HIDDEN_DOCSTRING",
    "NOTE",
    "looks_like_python_source",
    "prune",
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


def _is_source_of(text: str, handler: LanguageHandler) -> bool:
    """True when `text` is a block of `handler`'s language, not an output that merely contains some code."""
    lines = [ln for ln in text.split("\n") if ln.strip()]
    if len(lines) < MIN_LINES or _NOT_SOURCE.search(text):
        return False
    if len(_NUMBERED.findall(text)) > 0.4 * len(lines):
        return False
    return handler.score(text) >= handler.min_score


def looks_like_python_source(text: str) -> bool:
    """True when `text` is a block of Python source, not an output that merely contains some code."""
    return _is_source_of(text, _PYTHON)


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
    lines = text.split("\n")
    n = len(lines)
    wanted: list[Span] = [
        s
        for s in found
        if (comments if s.kind == "comment" else docstrings) and not handler.keep(s)
    ]

    for s in wanted:
        if s.kind == "comment" and s.first_row <= n:
            before = lines[s.first_row - 1][: s.col]
            lines[s.first_row - 1] = "" if not before.strip() else before.rstrip()
    for s in wanted:
        if s.kind == "docstring" and s.last_row <= n:
            first = text.split("\n")[s.first_row - 1]
            lines[s.first_row - 1] = (
                first[: len(first) - len(first.lstrip(" \t"))] + handler.hidden_doc
            )
            for i in range(s.first_row, s.last_row):
                lines[i] = ""

    out = "\n".join(lines)
    if len(text) - len(out) - len(NOTE) - 1 < min_saved_chars:
        return None
    if not handler.same_code(text, out):
        return None
    return out.rstrip("\n") + "\n" + NOTE + ("\n" if text.endswith("\n") else "")


def prune_python(
    text: str, *, comments: bool = True, docstrings: bool = True, min_saved_chars: int = 200
) -> str | None:
    """`prune` with the Python handler."""
    return prune(
        text, _PYTHON, comments=comments, docstrings=docstrings, min_saved_chars=min_saved_chars
    )

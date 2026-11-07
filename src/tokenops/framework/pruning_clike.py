"""Shared handler for C-style languages: turns the lexer's comments into spans, and decides which must stay.

A language subclass supplies its lexer switches (``CLexConfig``), the structure patterns that tell it from the others,
and a few doc-comment rules. Everything else lives here:

- a ``/** */`` block (and ``/*! */`` where that is a doc comment) that owns its lines is a doc comment;
- consecutive ``///`` or ``//!`` lines are one doc comment (a Go doc comment is the ``//`` block right above a
  declaration, which a subclass recognises);
- any other comment is hidden: a whole-line one becomes blank, a trailing one is trimmed;
- comments that tools read stay (``//go:build``, ``//nolint``, ``// NOLINT``, ``// SAFETY:``, ``/*! license */``, the cgo
  preamble above ``import "C"`` ...);
- the safety contract compares the code skeleton the lexer returns before and after.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from typing import Literal

from tokenops.framework.pruning_clex import lex_c_style
from tokenops.framework.pruning_types import CLexConfig, Span

HIDDEN_DOC = "/* (doc hidden) */"

# Comments that tools or people rely on: never hidden. Matched at the start of the comment text.
_KEEP_LINE = re.compile(
    r"//\s*(?:go:|nolint|noinspection|nosec|#nosec|\+build|line\s|export\s|NOSONAR|clang-format|"
    r"cppcheck|coverity|SAFETY:|fallthrough|falls through|vim:|-\*-|@formatter|lint:|rustfmt|clippy|"
    r"checkstyle|NON-NLS|noformat|SPDX-License-Identifier)",
    re.I,
)
_KEEP_BLOCK = re.compile(
    r"/\*\s*(?:NOLINT|NOSONAR|fallthrough|falls through|clang-format|cppcheck|coverity|-\*-|@formatter|"
    r"noinspection|SPDX-License-Identifier)",
    re.I,
)


class CStyleHandler:
    """Base for the Go, Java, Rust and C/C++ handlers. Subclasses set the class attributes below."""

    name = ""
    min_score = 4.0
    hidden_doc = HIDDEN_DOC
    cfg = CLexConfig()
    structure: re.Pattern[str] = re.compile(r"(?!)", re.M)  # lines that show this language
    slash_doc = True  # `///` and `//!` lines are doc comments
    bang_block_is_doc = (
        False  # `/*! */` is a doc comment (Rust); elsewhere it is a kept license block
    )
    cgo = False  # a comment right above `import "C"` is code (Go)

    def score(self, text: str) -> float:
        return float(len(self.structure.findall(text)))

    def group_is_doc(self, lines: list[str], last_row: int) -> bool:
        """A run of plain `//` lines ending at `last_row` (1-based) is a doc comment. Go overrides this."""
        return False

    # -- LanguageHandler ------------------------------------------------------------------------------------

    def spans(self, text: str) -> list[Span] | None:
        lexed = lex_c_style(text, self.cfg)
        if lexed is None:
            return None
        lines = text.split("\n")
        starts = [0]
        for ln in lines[:-1]:
            starts.append(starts[-1] + len(ln) + 1)

        def pos(off: int) -> tuple[int, int]:
            row = bisect_right(starts, off) - 1
            return row + 1, off - starts[row]

        found: list[Span] = []
        run: list[
            tuple[int, int, str]
        ] = []  # contiguous whole-line `//` comments: (row, col, text)

        def flush() -> None:
            found.extend(self._line_run(run, lines))
            run.clear()

        for c in lexed.comments:
            r1, c1 = pos(c.start)
            body = text[c.start : c.end]
            owns_start = not lines[r1 - 1][:c1].strip()
            if not c.block:
                if "\n" in body:  # continued by a trailing backslash: several rows, one comment
                    flush()
                    found.append(Span("comment", r1, pos(c.end)[0], c1, body))
                    continue
                if owns_start and run and run[-1][0] != r1 - 1:
                    flush()
                if owns_start:
                    run.append((r1, c1, body))
                    continue
                flush()
                found.append(Span("comment", r1, r1, c1, body))
                continue
            flush()
            r2, c2 = pos(c.end)
            owns_end = not lines[r2 - 1][c2:].strip()
            is_doc = owns_start and owns_end and self._block_is_doc(body)
            kind: Literal["comment", "docstring"] = "docstring" if is_doc else "comment"
            cgo = self.cgo and r2 < len(lines) and lines[r2].strip() == 'import "C"'
            found.append(Span(kind, r1, r2, c1, body, end_col=c2, significant=cgo))
        flush()
        return found

    def keep(self, span: Span) -> bool:
        if span.significant:
            return True
        body = span.text
        if body.startswith("/*!"):
            return not self.bang_block_is_doc
        return bool(_KEEP_LINE.match(body) if body.startswith("//") else _KEEP_BLOCK.match(body))

    def same_code(self, before: str, after: str) -> bool:
        a = lex_c_style(before, self.cfg)
        b = lex_c_style(after, self.cfg)
        return a is not None and b is not None and a.skeleton == b.skeleton

    # -- helpers --------------------------------------------------------------------------------------------

    def _block_is_doc(self, body: str) -> bool:
        if body.startswith("/*!"):
            return self.bang_block_is_doc
        return body.startswith("/**") and not body.startswith(("/**/", "/***"))

    def _line_is_doc(self, body: str) -> bool:
        if not self.slash_doc:
            return False
        return body.startswith("//!") or (body.startswith("///") and not body.startswith("////"))

    def _line_run(self, run: list[tuple[int, int, str]], lines: list[str]) -> list[Span]:
        """Spans for a run of consecutive whole-line `//` comments: sub-runs of the same kind become one span."""
        out: list[Span] = []
        i = 0
        while i < len(run):
            kind = self._line_kind(run[i][2])
            j = i + 1
            while j < len(run) and self._line_kind(run[j][2]) == kind:
                j += 1
            part = run[i:j]
            first, last = part[0], part[-1]
            if kind == "plain" and self.group_is_doc(lines, last[0]):
                kind = "doc"
            if kind == "doc":
                out.append(Span("docstring", first[0], last[0], first[1], first[2]))
            else:
                cgo = self.cgo and kind == "plain" and last[0] < len(lines)
                cgo = cgo and lines[last[0]].strip() == 'import "C"'
                out.extend(Span("comment", r, r, c, t, significant=cgo) for r, c, t in part)
            i = j
        return out

    def _line_kind(self, body: str) -> str:
        if _KEEP_LINE.match(body):
            return "keep"
        return "doc" if self._line_is_doc(body) else "plain"

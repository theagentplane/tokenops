"""Python handler for tool-output pruning: finds comments and provable docstrings in a text that may be a fragment.

A ``sed`` range can start or end inside a docstring, mid-block, or mid-statement. So a string is only reported as a
docstring when it is provably one from what is visible, and a text that does not lex cleanly is refused. Standard
library only: ``tokenize`` and ``ast``.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize

from tokenops.framework.pruning_types import Span

HIDDEN_DOCSTRING = '"""(docstring hidden)"""'

# Comments that tools read, or that mark the file's encoding: never hidden.
_KEEP = re.compile(
    r"#\s*(!|type:|noqa|pragma|fmt:|isort:|pylint:|flake8|mypy|pyright|-\*-|(?:en)?coding[:=])",
    re.I,
)
_STRUCTURE = re.compile(
    r"^\s*(def |class |async def |import |from \S+ import |return\b|if .*:$|elif .*:$|else:$|for .* in .*:$|"
    r"while .*:$|try:$|except\b.*:$|finally:$|with .*:$|raise\b|assert\b|yield\b|@\w[\w.]*(\(.*\))?$|pass$)",
    re.M,
)
_SKIP = (
    tokenize.COMMENT,
    tokenize.NL,
    tokenize.ENCODING,
    tokenize.INDENT,
    tokenize.DEDENT,
    tokenize.ENDMARKER,
)


class _Lexed:
    """Tokens of a text that may be a fragment, found on a copy with every line's indentation removed.

    A ``sed`` range can start mid-block and dedent to a level it never opened, which ``tokenize`` rejects, and it can end
    inside a bracket or a string. Where strings and comments are does not depend on indentation, so it is dropped for
    lexing and added back to the columns. A string that never closes at the end is reported, not an error; anything else
    odd (a stray quote from a text that starts inside a docstring) means "not clean Python" and the caller leaves the text.
    """

    def __init__(self, text: str) -> None:
        self.lines = text.split("\n")
        self.lead = [len(ln) - len(ln.lstrip(" \t")) for ln in self.lines]
        flat = "\n".join(ln.lstrip(" \t") for ln in self.lines)
        self.tokens: list[tokenize.TokenInfo] = []
        self.open_string: tuple[int, int] | None = None  # where a string that never closes starts
        self.ok = True
        try:
            for tok in tokenize.generate_tokens(io.StringIO(flat).readline):
                self.tokens.append(tok)
        except tokenize.TokenError as err:
            msg = str(err.args[0]) if err.args else ""
            pos = err.args[1] if len(err.args) > 1 else None
            if "multi-line string" in msg and pos:
                self.open_string = (pos[0], pos[1])
            elif "multi-line statement" not in msg:
                self.ok = False
        except (SyntaxError, ValueError):
            self.ok = False
        if any(t.type == tokenize.ERRORTOKEN for t in self.tokens):
            self.ok = False

    def col(self, row: int, col: int) -> int:
        """Column in the original text of a position in the indentation-free copy."""
        return col + self.lead[row - 1]

    def statements(self) -> list[list[tokenize.TokenInfo]]:
        """Significant tokens grouped by statement; the last group is a cut-off statement (empty if the text ended cleanly)."""
        groups: list[list[tokenize.TokenInfo]] = [[]]
        for t in self.tokens:
            if t.type in _SKIP:
                continue
            if t.type == tokenize.NEWLINE:
                groups.append([])
            else:
                groups[-1].append(t)
        return groups

    def docstrings(self) -> list[tuple[int, int]]:
        """(first_row, last_row) of each string that is provably a docstring: alone in its statement, and either the
        first statement of the text at column 0 (a module docstring) or directly after a ``def``/``class`` header."""
        groups = self.statements()
        found: list[tuple[int, int]] = []

        def after_header(i: int) -> bool:
            prev = groups[i - 1] if i > 0 else []
            return (
                bool(prev)
                and prev[0].string in ("def", "class", "async")
                and prev[-1].type == tokenize.OP
                and prev[-1].string == ":"
            )

        for i, g in enumerate(groups):
            if len(g) == 1 and g[0].type == tokenize.STRING:
                row = g[0].start[0]
                if (i == 0 and self.col(row, g[0].start[1]) == 0) or after_header(i):
                    found.append((row, g[0].end[0]))
        if (
            self.open_string
        ):  # the text ends inside a string; it is a docstring if it opens one at statement start
            row, col = self.open_string
            i = len(groups) - 1
            owns_line = not self.lines[row - 1][: self.col(row, col)].strip()
            if (
                not groups[i]
                and owns_line
                and (after_header(i) or (i == 0 and self.col(row, col) == 0))
            ):
                found.append((row, len(self.lines)))
        return found


def _dump_without_docstrings(text: str) -> str:
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and node.body
        ):
            first = node.body[0]
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                node.body = node.body[1:] or [ast.Pass()]
    return ast.dump(tree, include_attributes=False)


class PythonHandler:
    """Comments (``#``) and docstrings of Python source."""

    name = "python"
    min_score = 3.0  # structure lines (def, class, import, if ...:, return ...) the text must have
    hidden_doc = HIDDEN_DOCSTRING

    def score(self, text: str) -> float:
        return float(len(_STRUCTURE.findall(text)))

    def spans(self, text: str) -> list[Span] | None:
        lexed = _Lexed(text)
        if not lexed.ok:
            return None
        found = [
            Span(
                "comment",
                tok.start[0],
                tok.start[0],
                lexed.col(tok.start[0], tok.start[1]),
                tok.string,
            )
            for tok in lexed.tokens
            if tok.type == tokenize.COMMENT and tok.start[0] <= len(lexed.lines)
        ]
        found += [Span("docstring", first, last) for first, last in lexed.docstrings()]
        return found

    def keep(self, span: Span) -> bool:
        return span.kind == "comment" and bool(_KEEP.match(span.text))

    def same_code(self, before: str, after: str) -> bool:
        """The syntax trees minus docstrings are equal; a fragment that does not parse has nothing to compare."""
        try:
            before_tree = _dump_without_docstrings(before)
        except (SyntaxError, ValueError):
            return True
        try:
            return _dump_without_docstrings(after) == before_tree
        except (SyntaxError, ValueError):
            return False

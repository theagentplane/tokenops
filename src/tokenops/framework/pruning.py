"""Hide comments and docstrings in a tool result that is Python source, from the result text alone.

The pruner does not know the command that produced the text, and the text may be a fragment (a ``sed`` range can start or
end inside a docstring, mid-block, or mid-statement). So it only acts when the text *lexes cleanly as Python and has
Python's structure*, and it only hides a string it can prove is a docstring from what it can see. When in doubt it returns
``None`` and the result goes through untouched. It never changes a code line, and it keeps the number of lines the same
(a hidden block becomes blank lines), so line numbers the agent has seen or will cite still hold.

Pure, model-free and dependency-free: the standard library's ``tokenize`` and ``ast`` only.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize

HIDDEN_DOCSTRING = '"""(docstring hidden)"""'
NOTE = (
    "[TokenOps: comments and docstrings are hidden in this output; line numbers are unchanged. "
    "`grep -n` shows a specific comment or docstring line.]"
)

# Comments that tools read, or that mark the file's encoding: never hidden.
_KEEP = re.compile(
    r"#\s*(!|type:|noqa|pragma|fmt:|isort:|pylint:|flake8|mypy|pyright|-\*-|(?:en)?coding[:=])",
    re.I,
)

# Output that merely contains code lines: diffs, grep -n hits, test reports. Never pruned.
_NOT_SOURCE = re.compile(
    r"^(diff --git |@@ |\+\+\+ |--- [ab]/|={3,} \S.* ={3,}$|E {3}|[\w./\\-]+:\d+:)", re.M
)
_NUMBERED = re.compile(
    r"^\s*\d+[\t:|]\s", re.M
)  # cat -n / nl listings: most lines start with a number
_STRUCTURE = re.compile(
    r"^\s*(def |class |async def |import |from \S+ import |return\b|if .*:$|elif .*:$|else:$|for .* in .*:$|"
    r"while .*:$|try:$|except\b.*:$|finally:$|with .*:$|raise\b|assert\b|yield\b|@\w[\w.]*(\(.*\))?$|pass$)",
    re.M,
)
MIN_LINES = 8
MIN_STRUCTURE_LINES = 3
_SKIP = (
    tokenize.COMMENT,
    tokenize.NL,
    tokenize.ENCODING,
    tokenize.INDENT,
    tokenize.DEDENT,
    tokenize.ENDMARKER,
)


def looks_like_python_source(text: str) -> bool:
    """True when `text` is a block of Python source, not an output that merely contains some code."""
    lines = [ln for ln in text.split("\n") if ln.strip()]
    if len(lines) < MIN_LINES or _NOT_SOURCE.search(text):
        return False
    if len(_NUMBERED.findall(text)) > 0.4 * len(lines):
        return False
    return len(_STRUCTURE.findall(text)) >= MIN_STRUCTURE_LINES


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


def prune_python(
    text: str, *, comments: bool = True, docstrings: bool = True, min_saved_chars: int = 200
) -> str | None:
    """`text` with comments and/or docstrings hidden and the same number of lines, or None to leave it as it is.

    None when: it is not Python source, it does not lex cleanly, it would save fewer than `min_saved_chars` (after the
    note), or, when the whole text parses as Python, the syntax tree minus docstrings would differ."""
    if not (comments or docstrings) or not looks_like_python_source(text):
        return None
    lexed = _Lexed(text)
    if not lexed.ok:
        return None
    lines = list(lexed.lines)
    n = len(lines)

    if comments:
        for tok in lexed.tokens:
            if tok.type != tokenize.COMMENT or _KEEP.match(tok.string):
                continue
            row = tok.start[0]
            if row <= n:
                before = lines[row - 1][: lexed.col(row, tok.start[1])]
                lines[row - 1] = "" if not before.strip() else before.rstrip()

    if docstrings:
        for first, last in lexed.docstrings():
            if last > n:
                continue
            lines[first - 1] = lexed.lines[first - 1][: lexed.lead[first - 1]] + HIDDEN_DOCSTRING
            for i in range(first, last):
                lines[i] = ""

    out = "\n".join(lines)
    if len(text) - len(out) - len(NOTE) - 1 < min_saved_chars:
        return None
    try:
        before_tree = _dump_without_docstrings(text)
    except (SyntaxError, ValueError):
        before_tree = None  # a fragment does not parse: nothing to compare against
    if before_tree is not None:
        try:
            if _dump_without_docstrings(out) != before_tree:
                return None
        except (SyntaxError, ValueError):
            return None
    return out.rstrip("\n") + "\n" + NOTE + ("\n" if text.endswith("\n") else "")

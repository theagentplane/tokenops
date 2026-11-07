"""A lexer for POSIX and bash shell scripts that finds comments and nothing else.

A ``#`` starts a comment only at the start of a word: not inside quotes, not in ``${#var}``, ``$#``, ``${x#pat}`` or
``16#ff``, not after a backslash. Single quotes, double quotes (with ``$(...)`` and ``${...}`` inside), ``$'...'``,
backticks and here-documents are skipped as opaque text, so a ``#`` in a heredoc body is not a comment. It refuses a
text that ends inside a quote, a command substitution or a heredoc. A text that *starts* inside a heredoc body cannot be
told apart from code, which is why shell is not part of ``languages: "auto"``.
"""

from __future__ import annotations

import re

from tokenops.framework.pruning_types import CComment, CLexed

_COMMENT_AFTER = " \t\r\n;&|()"
_HEREDOC = re.compile(r"<<(-?)[ \t]*(?:'([^'\n]+)'|\"([^\"\n]+)\"|\\?([A-Za-z_][A-Za-z0-9_]*))")


class _ShellLexer:
    def __init__(self, text: str) -> None:
        self.t = text
        self.n = len(text)

    def single(self, i: int) -> int:
        k = self.t.find("'", i + 1)
        return -1 if k < 0 else k + 1

    def ansi(self, i: int) -> int:
        """``$'...'``: backslash escapes, `i` at the ``$``."""
        j = i + 2
        while j < self.n:
            if self.t[j] == "\\":
                j += 2
            elif self.t[j] == "'":
                return j + 1
            else:
                j += 1
        return -1

    def group(self, j: int, close: str) -> int:
        """End of a ``$(...)`` or ``${...}`` group whose body starts at `j`, skipping quotes and nested groups."""
        opener = "(" if close == ")" else "{"
        depth = 0
        while j < self.n:
            ch = self.t[j]
            if ch == "\\":
                j += 2
                continue
            if ch == "'":
                j = self.single(j)
            elif ch == '"':
                j = self.double(j)
            elif ch == opener:
                depth += 1
                j += 1
            elif ch == close:
                if depth == 0:
                    return j + 1
                depth -= 1
                j += 1
            else:
                j += 1
            if j < 0:
                return -1
        return -1

    def double(self, i: int) -> int:
        j = i + 1
        while j < self.n:
            ch = self.t[j]
            if ch == "\\":
                j += 2
            elif ch == '"':
                return j + 1
            elif ch == "$" and self.t[j + 1 : j + 2] in ("(", "{"):
                j = self.group(j + 2, ")" if self.t[j + 1] == "(" else "}")
                if j < 0:
                    return -1
            else:
                j += 1
        return -1

    def backtick(self, i: int) -> int:
        j = i + 1
        while j < self.n:
            if self.t[j] == "\\":
                j += 2
            elif self.t[j] == "`":
                return j + 1
            else:
                j += 1
        return -1

    def heredoc_bodies(
        self, i: int, pending: list[tuple[str, bool]]
    ) -> tuple[int, list[str]] | None:
        """Consume the bodies of the pending heredocs that start after the newline at `i`; (new index, pieces)."""
        pos, pieces = i + 1, []
        for delim, strip in pending:
            start = pos
            while True:
                if pos > self.n:
                    return None
                end = self.t.find("\n", pos)
                end = self.n if end < 0 else end
                line = self.t[pos:end].rstrip("\r")
                if (line.lstrip("\t") if strip else line) == delim:
                    pieces.append(self.t[start:end])
                    pos = end + 1
                    break
                if end >= self.n:
                    return None  # the text ends inside the heredoc
                pos = end + 1
        return min(pos - 1, self.n), pieces

    def run(self) -> CLexed | None:
        t, n = self.t, self.n
        comments: list[CComment] = []
        out: list[str] = []
        space = False
        pending: list[tuple[str, bool]] = []
        i = 0

        def put(piece: str) -> None:
            nonlocal space
            if space and out:
                out.append(" ")
            space = False
            out.append(piece)

        while i < n:
            c = t[i]
            if c == "\n" and pending:
                got = self.heredoc_bodies(i, pending)
                if got is None:
                    return None
                i, pieces = (
                    got  # `i` is now the newline that ends the last terminator line, or the end
                )
                pending = []
                space = True
                for piece in pieces:
                    put(piece)
                    space = True
            elif c in " \t\r\n":
                space = True
                i += 1
            elif c == "#" and (i == 0 or t[i - 1] in _COMMENT_AFTER):
                end = t.find("\n", i)
                end = n if end < 0 else end
                if t[end - 1 : end] == "\r":
                    end -= 1
                comments.append(CComment(i, end, False))
                space, i = True, end
            elif c == "\\":
                put(t[i : i + 2])
                i += 2
            elif c == "'":
                end = self.single(i)
                if end < 0:
                    return None
                put(t[i:end])
                i = end
            elif c == "$" and t.startswith("$'", i):
                end = self.ansi(i)
                if end < 0:
                    return None
                put(t[i:end])
                i = end
            elif c == '"':
                end = self.double(i)
                if end < 0:
                    return None
                put(t[i:end])
                i = end
            elif c == "`":
                end = self.backtick(i)
                if end < 0:
                    return None
                put(t[i:end])
                i = end
            elif c == "<" and t.startswith("<<", i) and not t.startswith("<<<", i):
                m = _HEREDOC.match(t, i)
                if m:
                    delim = m.group(2) or m.group(3) or m.group(4)
                    pending.append((delim, m.group(1) == "-"))
                    put(m.group(0))
                    i = m.end()
                else:
                    put("<<")
                    i += 2
            else:
                put(c)
                i += 1
        if pending:
            return None  # the text ends before the heredoc body starts
        return CLexed(comments, "".join(out))


def lex_shell(text: str) -> CLexed | None:
    """Comments and code skeleton of shell `text`, or None when it cannot be lexed with certainty."""
    return _ShellLexer(text).run()

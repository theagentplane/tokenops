"""A lexer for SQL that finds ``--`` and ``/* */`` comments and refuses where dialects disagree.

Strings (``'it''s'``), quoted identifiers (``"x"``, `` `x` ``) and Postgres dollar quotes (``$tag$ ... $tag$``) are skipped,
so a ``--`` inside them is not a comment. Block comments nest, as in the standard and Postgres. It refuses: a string whose
closing quote follows a backslash (MySQL and ``E'...'`` strings read that as an escape, standard SQL does not), a
MySQL-style ``# comment``, an unterminated string or dollar quote, and a text that starts or ends inside a block comment.
"""

from __future__ import annotations

import re

from tokenops.framework.pruning_types import CComment, CLexed

_DOLLAR = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)?\$")


def _quoted(text: str, i: int, quote: str, allow_backslash_before_close: bool) -> int:
    """End of the quoted token at `i` (a doubled quote is an escaped one), or -1."""
    j, n = i + 1, len(text)
    while j < n:
        if text[j] == quote:
            if text[j + 1 : j + 2] == quote:
                j += 2
                continue
            if text[j - 1] == "\\" and not allow_backslash_before_close:
                return -1
            return j + 1
        j += 1
    return -1


def lex_sql(text: str) -> CLexed | None:
    """Comments and code skeleton of SQL `text`, or None when it cannot be lexed with certainty."""
    n = len(text)
    comments: list[CComment] = []
    out: list[str] = []
    space = False
    i = 0

    def put(piece: str) -> None:
        nonlocal space
        if space and out:
            out.append(" ")
        space = False
        out.append(piece)

    while i < n:
        c = text[i]
        if c.isspace():
            space = True
            i += 1
        elif text.startswith("--", i):
            end = text.find("\n", i)
            end = n if end < 0 else end
            if text[end - 1 : end] == "\r":
                end -= 1
            comments.append(CComment(i, end, False))
            space, i = True, end
        elif text.startswith("/*", i):
            depth, j = 1, i + 2
            while j < n and depth:
                if text.startswith("*/", j):
                    depth -= 1
                    j += 2
                elif text.startswith("/*", j):
                    depth += 1
                    j += 2
                else:
                    j += 1
            if depth:
                return None  # the text ends inside a block comment
            comments.append(CComment(i, j, True))
            space, i = True, j
        elif c == "*" and text.startswith("*/", i):
            return None  # the text starts inside a block comment
        elif c in "'\"`":
            end = _quoted(text, i, c, allow_backslash_before_close=c != "'")
            if end < 0:
                return None
            put(text[i:end])
            i = end
        elif c == "$" and (m := _DOLLAR.match(text, i)):
            close = m.group(0)
            k = text.find(close, m.end())
            if k < 0:
                return None
            put(text[i : k + len(close)])
            i = k + len(close)
        elif c == "#" and text[i + 1 : i + 2] in (" ", "\t", ""):
            return None  # a MySQL comment; the dialect is not one this lexer reads
        else:
            put(c)
            i += 1
    return CLexed(comments, "".join(out))

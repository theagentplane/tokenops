"""A lexer for C-style languages (Go, Java, Rust, C and C++) that finds comments and nothing else.

It walks the text once, skipping string and character literals so that a comment marker inside a string is not a
comment. It returns ``None`` (refuse) whenever it cannot be sure: a block comment that never closes (the text ends
inside one), a stray ``*/`` (the text starts inside one), or a string that never closes. A hand-written lexer on the
standard library, per language switches in ``CLexConfig``.
"""

from __future__ import annotations

import re

from tokenops.framework.pruning_types import CComment, CLexConfig, CLexed

_RUST_RAW = re.compile(r'(?:br|cr|r)(#*)"')
_CPP_RAW = re.compile(r'(?:u8|u|U|L)?R"([^ ()\\\t\v\f\n]{0,16})\(')
_RUST_ESCAPED_CHAR_MAX = 12  # '\u{10FFFF}' is the longest


def _ident_boundary(text: str, i: int) -> bool:
    return i == 0 or not (text[i - 1].isalnum() or text[i - 1] == "_")


def _plain_string(text: str, i: int, quote: str, multiline: bool) -> int | None:
    """End (exclusive) of a quoted literal opened at `i`, or None when it does not close where it may."""
    j, n = i + 1, len(text)
    while j < n:
        ch = text[j]
        if ch == "\\":
            j += 2
        elif ch == quote:
            return j + 1
        elif ch == "\n" and not multiline:
            return None
        else:
            j += 1
    return None


def _text_block(text: str, i: int) -> int | None:
    j, n = i + 3, len(text)
    while j < n:
        if text[j] == "\\":
            j += 2
        elif text.startswith('"""', j):
            return j + 3
        else:
            j += 1
    return None


def _raw_end(text: str, start: int, closing: str) -> int | None:
    k = text.find(closing, start)
    return None if k < 0 else k + len(closing)


def _rust_char(text: str, i: int) -> int | None:
    """End of a Rust char literal at `i`, or None when the quote is a lifetime or label."""
    n = len(text)
    if i + 1 < n and text[i + 1] == "\\":
        k = text.find("'", i + 3, i + 3 + _RUST_ESCAPED_CHAR_MAX)
        return None if k < 0 else k + 1
    if i + 2 < n and text[i + 2] == "'" and text[i + 1] not in "'\n":
        return i + 3
    return None


def _is_digit_separator(text: str, i: int) -> bool:
    """C++14 ``1'000``: the quote follows a token that starts with a digit."""
    j = i
    while j > 0 and (text[j - 1].isalnum() or text[j - 1] in "_'"):
        j -= 1
    return j < i and text[j].isdigit() and i + 1 < len(text) and text[i + 1].isalnum()


def lex_c_style(text: str, cfg: CLexConfig) -> CLexed | None:
    """Comments and code skeleton of `text`, or None when the text cannot be lexed with certainty."""
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
        elif c == "/" and text.startswith("//", i):
            end = text.find("\n", i)
            while cfg.line_continuation and end > 0 and text[end - 1 : end] == "\\":
                nxt = text.find("\n", end + 1)
                if (
                    nxt < 0
                ):  # the continuation line is the last, unterminated one (or there is none)
                    end = n if n > end + 1 else end
                    break
                end = nxt
            end = n if end < 0 else end
            if text[end - 1 : end] == "\r":
                end -= 1
            comments.append(CComment(i, end, False))
            space, i = True, end
        elif c == "/" and text.startswith("/*", i):
            depth, j = 1, i + 2
            while j < n and depth:
                if text.startswith("*/", j):
                    depth -= 1
                    j += 2
                elif cfg.nested_comments and text.startswith("/*", j):
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
        else:
            end = _literal_end(text, i, cfg)
            if end == -1:
                return None
            if end > i:
                put(text[i:end])
                i = end
            else:
                put(c)
                i += 1
    return CLexed(comments, "".join(out))


def _literal_end(text: str, i: int, cfg: CLexConfig) -> int:
    """End of the string or char literal that starts at `i`; `i` if there is none; -1 if it does not close."""
    c = text[i]
    if c == "`" and cfg.go_raw_strings:
        k = text.find("`", i + 1)
        return -1 if k < 0 else k + 1
    if c in "rbc" and cfg.rust_raw_strings and _ident_boundary(text, i):
        m = _RUST_RAW.match(text, i)
        if m:
            end = _raw_end(text, m.end(), '"' + m.group(1))
            return -1 if end is None else end
    if c in "uULR" and cfg.cpp_raw_strings and _ident_boundary(text, i):
        m = _CPP_RAW.match(text, i)
        if m:
            end = _raw_end(text, m.end(), ")" + m.group(1) + '"')
            return -1 if end is None else end
    if c == '"':
        if cfg.text_blocks and text.startswith('"""', i):
            end = _text_block(text, i)
        else:
            end = _plain_string(text, i, '"', cfg.multiline_strings)
        return -1 if end is None else end
    if c == "'":
        if cfg.rust_chars:
            end = _rust_char(text, i)
            return i if end is None else end  # a lifetime is code
        if cfg.digit_separators and _is_digit_separator(text, i):
            return i
        end = _plain_string(text, i, "'", False)
        return -1 if end is None else end
    return i

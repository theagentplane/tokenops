"""A lexer for JavaScript and TypeScript that finds comments, and refuses whenever it cannot be sure.

The hard part of lexing JavaScript is that ``/`` is either a division or the start of a regular expression literal, and
a regex can contain ``//`` or ``/*``. The decision is made from the previous token, as a JavaScript parser does; a case
that stays ambiguous (``/`` right after ``}``) refuses the whole text. Template literals are skipped with their nested
``${ ... }``; a comment or a ``/`` inside such an expression refuses. JSX is refused, because its text children can contain
``//`` and apostrophes. A text that starts or ends inside a block comment or a string is refused. Standard library only.
"""

from __future__ import annotations

from tokenops.framework.pruning_types import CComment, CLexed

# After one of these words a ``/`` starts a regular expression; after any other word it is a division.
_REGEX_AFTER_WORD = frozenset(
    "return typeof instanceof in of new delete void throw case do else yield await".split()
)


def _is_word_char(ch: str) -> bool:
    return ch.isalnum() or ch in "_$"


class _JsLexer:
    def __init__(self, text: str) -> None:
        self.t = text
        self.n = len(text)
        self.comments: list[CComment] = []
        self.out: list[str] = []
        self.space = False
        self.regex_ok: bool | None = True  # None: right after `}`, where `/` cannot be classified

    def put(self, piece: str) -> None:
        if self.space and self.out:
            self.out.append(" ")
        self.space = False
        self.out.append(piece)

    # -- literals: each returns the end (exclusive) of the literal at `i`, or -1 --------------------------------

    def string(self, i: int) -> int:
        q, j = self.t[i], i + 1
        while j < self.n:
            ch = self.t[j]
            if ch == "\\":
                j += 2
            elif ch == q:
                return j + 1
            elif ch == "\n":
                return -1
            else:
                j += 1
        return -1

    def regex(self, i: int) -> int:
        j, in_class = i + 1, False
        while j < self.n:
            ch = self.t[j]
            if ch == "\\":
                j += 2
                continue
            if ch == "\n":
                return -1
            if ch == "[":
                in_class = True
            elif ch == "]":
                in_class = False
            elif ch == "/" and not in_class:
                j += 1
                while j < self.n and _is_word_char(self.t[j]):
                    j += 1  # flags
                return j
            j += 1
        return -1

    def template(self, i: int) -> int:
        j = i + 1
        while j < self.n:
            ch = self.t[j]
            if ch == "\\":
                j += 2
            elif ch == "`":
                return j + 1
            elif ch == "$" and self.t.startswith("${", j):
                j = self.expression_end(j + 2)
                if j < 0:
                    return -1
            else:
                j += 1
        return -1

    def expression_end(self, j: int) -> int:
        """End of a ``${ ... }`` expression that starts at `j`. A ``/`` (comment, regex or division) refuses."""
        depth = 0
        while j < self.n:
            ch = self.t[j]
            if ch == "/":
                return -1
            if ch in "'\"":
                j = self.string(j)
            elif ch == "`":
                j = self.template(j)
            elif ch == "{":
                depth += 1
                j += 1
            elif ch == "}":
                if depth == 0:
                    return j + 1
                depth -= 1
                j += 1
            else:
                j += 1
            if j < 0:
                return -1
        return -1

    # -- main loop ----------------------------------------------------------------------------------------------

    def run(self) -> CLexed | None:
        t, n = self.t, self.n
        i = 0
        if t.startswith("#!"):
            i = t.find("\n") if "\n" in t else n
            self.put(t[:i])
        while i < n:
            c = t[i]
            if c.isspace():
                self.space = True
                i += 1
            elif c == "/" and t.startswith("//", i):
                end = t.find("\n", i)
                end = n if end < 0 else end
                if t[end - 1 : end] == "\r":
                    end -= 1
                self.comments.append(CComment(i, end, False))
                self.space, i = True, end
            elif c == "/" and t.startswith("/*", i):
                end = t.find("*/", i + 2)
                if end < 0:
                    return None  # the text ends inside a block comment
                self.comments.append(CComment(i, end + 2, True))
                self.space, i = True, end + 2
            elif c == "*" and t.startswith("*/", i):
                return None  # the text starts inside a block comment
            elif c == "/":
                if self.regex_ok is None:
                    return None  # `}` then `/`: a division or a regex, cannot tell
                if self.regex_ok:
                    end = self.regex(i)
                    if end < 0:
                        return None
                    self.put(t[i:end])
                    self.regex_ok, i = False, end
                else:
                    self.put("/")
                    self.regex_ok, i = True, i + 1
            elif c in "'\"" or c == "`":
                end = self.string(i) if c != "`" else self.template(i)
                if end < 0:
                    return None
                self.put(t[i:end])
                self.regex_ok, i = False, end
            elif _is_word_char(c):
                j = i + 1
                while j < n and _is_word_char(t[j]):
                    j += 1
                word = t[i:j]
                after_dot = bool(self.out) and self.out[-1] == "."
                self.put(word)
                self.regex_ok = word in _REGEX_AFTER_WORD and not after_dot
                i = j
            elif c == "<" and self.regex_ok and t[i + 1 : i + 2].isalpha():
                return (
                    None  # `<Tag` where an expression starts: JSX, or a TS angle-bracket assertion
                )
            elif c in ")]":
                self.put(c)
                self.regex_ok, i = False, i + 1
            elif c == "}":
                self.put(c)
                self.regex_ok, i = None, i + 1
            elif c in "+-" and t.startswith(c * 2, i):
                self.put(c * 2)  # ++ and -- : postfix, so a division may follow
                self.regex_ok, i = False, i + 2
            elif c == ".":
                self.put(c)
                self.regex_ok, i = False, i + 1
            else:
                self.put(c)
                self.regex_ok, i = True, i + 1
        skeleton = "".join(self.out)
        if "</" in skeleton or "/>" in skeleton:
            return None  # JSX
        return CLexed(self.comments, skeleton)


def lex_js(text: str) -> CLexed | None:
    """Comments and code skeleton of JavaScript or TypeScript `text`, or None when it cannot be lexed with certainty."""
    return _JsLexer(text).run()

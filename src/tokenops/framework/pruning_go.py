"""Go handler for tool-output pruning.

A Go doc comment is the ``//`` block directly above a declaration. Directives (``//go:build``, ``//go:generate``,
``//go:embed``, ``//nolint``, ``//export``) stay, and so does the comment above ``import "C"``, which is cgo code.
"""

from __future__ import annotations

import re

from tokenops.framework.pruning_clike import CStyleHandler
from tokenops.framework.pruning_types import CLexConfig

_STRUCTURE = re.compile(
    r"^(?:package \w+\s*$|import (?:\(|\"|\w+ \")|func (?:\([^)]*\) )?\w+[\[(]|type \w+ (?:struct|interface)\b"
    r"|type \w+ [\w\[\]*.]+$)"
    r"|^\s*(?:[\w, .\[\]*]+ := |defer |go (?:func|\w+\()|if err != nil|for .*\brange\b|(?:var|const) (?:\(|\w+ [\w\[\]*.]+(?: =.*)?$))",
    re.M,
)
_DECLARATION = re.compile(r"(?:func|type|var|const|package)\b")


class GoHandler(CStyleHandler):
    name = "go"
    cfg = CLexConfig(go_raw_strings=True)
    structure = _STRUCTURE
    slash_doc = False
    cgo = True

    def group_is_doc(self, lines: list[str], last_row: int) -> bool:
        return last_row < len(lines) and bool(_DECLARATION.match(lines[last_row]))

"""Rust handler for tool-output pruning: nested block comments, ``///`` ``//!`` ``/** */`` ``/*! */`` doc comments.

``// SAFETY:`` comments stay: they justify an ``unsafe`` block and are cheap. ``#[doc = "..."]`` is an attribute, so code.
"""

from __future__ import annotations

import re

from tokenops.framework.pruning_clike import CStyleHandler
from tokenops.framework.pruning_types import CLexConfig

_VIS = r"(?:pub(?:\([\w: ]+\))?\s+)?"
_STRUCTURE = re.compile(
    rf"^\s*{_VIS}(?:const\s+)?(?:async\s+)?(?:unsafe\s+)?(?:extern\s+\"\w+\"\s+)?fn\s+\w+"
    rf"|^\s*pub(?:\([\w: ]+\))?\s+(?:struct|enum|trait|mod|type|const|static|use)\b"
    rf"|^\s*(?:unsafe\s+)?impl\b|^\s*use\s+[\w:{{]+::|^\s*let\s+(?:mut\s+)?[\w(]|^\s*#!?\[\w+"
    r"|^\s*match\s+.*\{$|\)\s+->\s*\S",
    re.M,
)


class RustHandler(CStyleHandler):
    name = "rust"
    cfg = CLexConfig(
        nested_comments=True, multiline_strings=True, rust_raw_strings=True, rust_chars=True
    )
    structure = _STRUCTURE
    bang_block_is_doc = True

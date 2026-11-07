"""Java handler for tool-output pruning: ``//`` comments, ``/* */`` comments, Javadoc, text blocks."""

from __future__ import annotations

import re

from tokenops.framework.pruning_clike import CStyleHandler
from tokenops.framework.pruning_types import CLexConfig

_MODS = r"(?:(?:public|protected|private|abstract|final|static|synchronized|default)\s+)"
_STRUCTURE = re.compile(
    r"^package [\w.]+;|^import (?:static )?[\w.*]+;|^\s*@[A-Z]\w*(?:\(.*\))?\s*$"
    rf"|^\s*(?:public|protected|private)\s+{_MODS}*[\w<>\[\],.? ]+\s+\w+\s*[(=;]"
    rf"|^\s*{_MODS}+(?:class|interface|enum|record)\s+\w+|\b(?:extends|implements)\s+\w+"
    r"|\bSystem\.(?:out|err)\.|\bthrows\s+\w+|\bpublic\s+static\s+void\s+main",
    re.M,
)


class JavaHandler(CStyleHandler):
    name = "java"
    cfg = CLexConfig(text_blocks=True)
    structure = _STRUCTURE

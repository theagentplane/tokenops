"""C and C++ handler for tool-output pruning.

``#pragma``, ``#if 0`` blocks and preprocessor lines are code, so they are never touched. A ``//`` comment that ends in a
backslash continues on the next line. Raw strings (``R"x(...)x"``) and digit separators (``1'000``) are handled by the lexer.
"""

from __future__ import annotations

import re

from tokenops.framework.pruning_clike import CStyleHandler
from tokenops.framework.pruning_types import CLexConfig

_NOT_OTHER = r"(?!func\b|fn\b|def\b|pub\b|public\b|private\b|protected\b|static\s+void\s+main)"
_STRUCTURE = re.compile(
    r"^\s*#\s*(?:include|define|undef|ifdef|ifndef|if|elif|else|endif|pragma|error)\b"
    r"|^\s*(?:typedef\b|namespace\b|template\s*<|extern\s+\"C\")"
    r"|^\s*(?:struct|union|enum|class)\s+\w+\s*(?::[^{]*)?\{?$"
    rf"|^{_NOT_OTHER}[A-Za-z_][\w\s\*&:<>,~]*\s[\*&]*\w+(?:::\w+)*\([^;{{}}]*\)\s*(?:const\s*)?(?:\{{|$)"
    r"|\b(?:nullptr|NULL)\b|\bstd::\w+|\w->\w|\b(?:printf|fprintf|malloc|calloc|free|sizeof)\s*\(",
    re.M,
)


class CHandler(CStyleHandler):
    name = "c"
    cfg = CLexConfig(line_continuation=True, cpp_raw_strings=True, digit_separators=True)
    structure = _STRUCTURE

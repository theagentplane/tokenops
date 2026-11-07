"""Shell handler for tool-output pruning: ``#`` comments in sh, bash and zsh scripts.

Shell has no doc comments, so every comment is hidden except the ones tools read: the shebang (any ``#!`` line),
``# shellcheck``, ``# shfmt``, editor modelines and ``# SPDX-License-Identifier``. A text with a markdown fence is never
treated as a script (a README with a ``bash`` block is documentation, and its ``#`` lines are headings).

Not part of ``languages: "auto"``: a text that starts inside a heredoc body looks like code and would have its
``#`` lines hidden, and a text window cannot show that. Enable it by name.
"""

from __future__ import annotations

import re

from tokenops.framework.pruning_clike import CStyleHandler
from tokenops.framework.pruning_shlex import lex_shell
from tokenops.framework.pruning_types import CLexed

_KEEP_LINE = re.compile(
    r"#\s*(?:!|shellcheck|shfmt|vim?:|vi:|-\*-|SPDX-License-Identifier|bashate|nolint|shellspec)",
    re.I,
)
_STRUCTURE = re.compile(
    r"^#!\s*/(?:usr/)?(?:local/)?bin/(?:env\s+)?(?:ba|z|da|k)?sh\b"
    r"|^\s*(?:if|elif)\s.*;\s*then\s*$|^\s*(?:then|fi|done|esac|do)\s*$|^\s*(?:for|select)\s+\w+\s+in\s"
    r"|^\s*while\s+.*;\s*do\s*$|^\s*case\s+.*\s+in\s*$|^\s*(?:function\s+\w+|\w+\s*\(\)\s*)\{?\s*$"
    r"|^\s*(?:export|local|readonly|declare|set|source|unset|shift|trap|exit|echo|printf|cat|cd|mkdir|rm|cp|mv|chmod|exec)\s"
    r"|^\s*\w+=(?:\"|'|\$|\w)|\$\{\w+[^}]*\}|\s\|\|\s|\s&&\s|2>&1|>/dev/null|\[\[\s",
    re.M,
)


class ShellHandler(CStyleHandler):
    name = "shell"
    structure = _STRUCTURE
    keep_line = _KEEP_LINE
    slash_doc = False

    def lex(self, text: str) -> CLexed | None:
        if "```" in text:
            return None
        return lex_shell(text)

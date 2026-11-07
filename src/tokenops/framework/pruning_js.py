"""JavaScript and TypeScript handler for tool-output pruning.

JSDoc (``/** */``) is the doc comment. In plain JavaScript it also carries types (``@param {string} x``, ``@type``,
``@typedef``) that ``tsc --checkJs`` reads, so by default a block comment with a type tag stays; ``keep_jsdoc_types=False``
hides it too (right for TypeScript, where the types are in the code). Tool comments stay: ``@ts-ignore``,
``@ts-expect-error``, ``eslint-disable``, ``/// <reference>``, ``// @flow``, ``//# sourceMappingURL``, ``/*! license */``,
``@license`` and ``@preserve``.
"""

from __future__ import annotations

import re

from tokenops.framework.pruning_clike import CStyleHandler
from tokenops.framework.pruning_jslex import lex_js
from tokenops.framework.pruning_types import CLexed, Span

_KEEP_LINE = re.compile(
    r"//\s*(?:@ts-|@flow|@jsx|@license|@preserve|eslint|istanbul|prettier-ignore|jshint|biome-|"
    r"noinspection|webpackChunkName|/\s*<(?:reference|amd)|#\s*source|SPDX-License-Identifier|"
    r"c8 ignore|v8 ignore)|//[/#]\s*<?(?:reference|amd|sourceMappingURL|sourceURL)",
    re.I,
)
_KEEP_BLOCK = re.compile(
    r"/\*\*?\s*(?:@license|@preserve|@flow|@jsx|eslint|istanbul|jshint|global\b|webpack|biome-|c8 |v8 |"
    r"SPDX-License-Identifier)|/\*+\s*[\s*]*@(?:license|preserve)\b",
    re.I,
)
_JSDOC_TYPES = re.compile(
    r"@(?:type|param|returns?|typedef|property|prop|throws|this|extends|implements|callback|enum)\s*\{"
    r"|@(?:template|satisfies|import)\b"
)
_STRUCTURE = re.compile(
    r"^\s*(?:import\s.*\sfrom\s+['\"]|import\s+['\"]|export\s+(?:default\b|const\b|let\b|async\b|function\b|class\b|"
    r"type\b|interface\b|enum\b|\{|\*)|(?:async\s+)?function\s*\*?\s*[\w$]*\s*\(|class\s+\w+(?:\s+extends\s+[\w.$]+)?\s*\{"
    r"|(?:const|let|var)\s+[\w${},\s\[\]]+(?::\s*[\w<>\[\]|. ]+)?=\s*\S"
    r"|interface\s+\w+|type\s+\w+(?:<.*>)?\s*=|declare\s+(?:module|const|function|global)\b)"
    r"|\bmodule\.exports\b|\brequire\(['\"]|=>\s*[{(]?\s*$|\bconsole\.(?:log|error|warn)\(|\bawait\s+\w",
    re.M,
)


class JsHandler(CStyleHandler):
    name = "js"
    structure = _STRUCTURE
    keep_line = _KEEP_LINE
    keep_block = _KEEP_BLOCK
    slash_doc = False  # `///` in TypeScript is a directive, kept above

    def __init__(self, keep_jsdoc_types: bool = True) -> None:
        self.keep_jsdoc_types = keep_jsdoc_types

    def lex(self, text: str) -> CLexed | None:
        return lex_js(text)

    def keep(self, span: Span) -> bool:
        if super().keep(span):
            return True
        return self.keep_jsdoc_types and bool(_JSDOC_TYPES.search(span.text))

"""SQL handler for tool-output pruning: ``--`` and ``/* */`` comments.

SQL has no doc comments (``COMMENT ON`` is a statement), so every comment is hidden except the ones a tool or the server
reads: optimizer hints (``/*+ ... */``), MySQL conditional comments (``/*!40101 ... */``, which are executed), migration
markers (``-- +goose Up``, ``-- migrate:up``, ``-- name: Query :one`` for sqlc), and linter directives (``-- noqa``,
``-- sqlfluff:``).
"""

from __future__ import annotations

import re

from tokenops.framework.pruning_clike import CStyleHandler
from tokenops.framework.pruning_sqllex import lex_sql
from tokenops.framework.pruning_types import CLexed

_KEEP_LINE = re.compile(
    r"--\s*(?:\+goose|\+migrate|migrate:|name:|noqa|sqlfluff|fmt:|nolint|liquibase|changeset|flyway|SPDX-License-Identifier|@)",
    re.I,
)
_KEEP_BLOCK = re.compile(r"/\*[+!]|/\*\s*(?:SPDX-License-Identifier|nolint|noqa)", re.I)
_STRUCTURE = re.compile(
    r"^\s*(?:select\b|insert\s+into\b|update\s+\S+\s+set\b|delete\s+from\b|create\s+(?:or\s+replace\s+)?"
    r"(?:unique\s+)?(?:temp(?:orary)?\s+)?(?:table|index|view|materialized\s+view|function|trigger|procedure|"
    r"extension|type|sequence|schema|database)\b|alter\s+table\b|drop\s+(?:table|index|view|schema)\b|"
    r"from\s+\S|where\s|group\s+by\b|order\s+by\b|(?:left\s+|right\s+|inner\s+|outer\s+|cross\s+)?join\s|"
    r"with\s+\w+\s+as\s*\(|begin\s*;|commit\s*;|on\s+conflict\b|returning\b)"
    r"|\bprimary\s+key\b|\bforeign\s+key\b|\bnot\s+null\b|\breferences\s+\w+\s*\(",
    re.M | re.I,
)


class SqlHandler(CStyleHandler):
    name = "sql"
    structure = _STRUCTURE
    keep_line = _KEEP_LINE
    keep_block = _KEEP_BLOCK
    slash_doc = False

    def lex(self, text: str) -> CLexed | None:
        return lex_sql(text)

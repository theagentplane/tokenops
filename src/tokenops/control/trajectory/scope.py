"""Scope keys and input normalization for trajectory hint lookup."""

from __future__ import annotations

import hashlib
import re
from typing import Mapping, Sequence

from tokenops.control.models import RunRegistration
from tokenops.control.policies._util import simhash64

_WS = re.compile(r"\s+")


def simhash_as_sqlite(v: int) -> int:
    """Store SimHash as signed 64-bit for SQLite INTEGER."""
    v &= (1 << 64) - 1
    if v >= (1 << 63):
        return v - (1 << 64)
    return v


def simhash_from_sqlite(v: int) -> int:
    if v < 0:
        return v + (1 << 64)
    return v


def normalize_input(text: str) -> str:
    """Deterministic normalization for cache keys — no tokenizer, no model."""
    return _WS.sub(" ", text.strip().lower())


def input_hash(text: str) -> str:
    return hashlib.sha256(normalize_input(text).encode()).hexdigest()


def input_simhash(text: str) -> int:
    return simhash64(normalize_input(text))


def scope_key(
    registration: RunRegistration,
    agent: str,
    scope_dims: Sequence[str],
) -> str:
    """Build a stable partition key from registration + agent."""
    parts: list[str] = []
    for dim in sorted(scope_dims):
        if dim == "intent":
            val = registration.intent or "_none"
        elif dim == "agent":
            val = agent or "_none"
        else:
            val = registration.user_dims.get(dim, "_none")
        parts.append(f"{dim}={val}")
    return "|".join(parts)


def scope_from_tags(
    *,
    intent: str,
    agent: str,
    tags: Mapping[str, str],
    scope_dims: Sequence[str],
) -> str:
    """Scope key when only Attribution tags are available (intent lives in tags)."""
    reg = RunRegistration(run_id="", intent=intent, user_dims=dict(tags))
    return scope_key(reg, agent, scope_dims)

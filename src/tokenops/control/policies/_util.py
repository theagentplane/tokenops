"""Deterministic, model-free helpers shared by behavioural detectors.

All hot-path safe: no tokenizer, no network, no model. Each is small and pure so the
detectors stay trivially testable.
"""

from __future__ import annotations

import json
import re
from collections import Counter


def edit_distance(a: str, b: str) -> int:
    """Levenshtein distance — for tool_fix 'did you mean'. O(len(a)*len(b))."""
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def did_you_mean(name: str, registry) -> str | None:
    """Closest registry entry within a small edit distance, else None."""
    best, best_d = None, 99
    for cand in registry:
        d = edit_distance(name, cand)
        if d < best_d:
            best, best_d = cand, d
    # only suggest if it's a plausible typo (≤ ~1/3 of the length)
    return best if best is not None and best_d <= max(1, len(name) // 3) else None


def est_tokens(payload: object) -> int:
    """Content-aware token estimate. ``len/4`` for natural-language text, ``len/2.8`` for
    structured/JSON/code (denser tokenization). Unknown/structured defaults to 2.8 so a
    large payload is never under-counted. No tokenizer on the hot path."""
    if isinstance(payload, str):
        text, divisor = payload, 4.0
    else:
        text, divisor = json.dumps(payload, default=str), 2.8  # structured → smaller divisor
    return int(len(text) / divisor)


_WORD = re.compile(r"\S+")


def max_ngram_repeat(text: str, n: int = 3) -> int:
    """Largest count of any repeated n-gram of words. A degenerate loop shows up as a high
    repeat count of the same n-gram."""
    words = _WORD.findall(text)
    if len(words) < n:
        return 0
    grams = Counter(tuple(words[i : i + n]) for i in range(len(words) - n + 1))
    return max(grams.values())


def single_token_domination(text: str) -> float:
    """Fraction of output made up of its single most common word (0..1). A value near 1
    means one token dominates — another runaway signature."""
    words = _WORD.findall(text)
    if not words:
        return 0.0
    return Counter(words).most_common(1)[0][1] / len(words)


def simhash64(text: str) -> int:
    """A 64-bit SimHash fingerprint of a text. Two texts are near-duplicates if the Hamming
    distance of their fingerprints is small. Deterministic, no model."""
    import hashlib

    v = [0] * 64
    for tok in _WORD.findall(text.lower()):
        h = int.from_bytes(hashlib.blake2b(tok.encode(), digest_size=8).digest(), "big")
        for i in range(64):
            v[i] += 1 if (h >> i) & 1 else -1
    out = 0
    for i in range(64):
        if v[i] > 0:
            out |= 1 << i
    return out


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")

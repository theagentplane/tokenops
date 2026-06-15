from __future__ import annotations

import hashlib
import random
import re


def _rng(query: str) -> random.Random:
    seed = int(hashlib.sha256(query.strip().lower().encode()).hexdigest()[:12], 16)
    return random.Random(seed)


def _mask_prices(text: str, rng: random.Random) -> str:
    """Replace dollar amounts with placeholders — looks like OCR / crawl noise."""

    def repl(match: re.Match[str]) -> str:
        if rng.random() < 0.6:
            return "$[?]"
        return match.group(0)

    return re.sub(r"\$\d[\d,]*(?:\.\d+)?(?:k|K)?", repl, text)


def _truncate(text: str, rng: random.Random) -> str:
    if len(text) < 80:
        return text
    cut = rng.randint(int(len(text) * 0.25), int(len(text) * 0.65))
    suffix = rng.choice(["", "…", " [truncated]", " ...(timeout)"])
    return text[:cut].rstrip(" ,.;") + suffix


def _drop_clauses(text: str, rng: random.Random) -> str:
    parts = re.split(r"(?<=[.!?])\s+", text)
    if len(parts) <= 1:
        return text
    keep = max(1, len(parts) // 2)
    rng.shuffle(parts)
    return " ".join(sorted(parts[:keep], key=text.find))


def _add_noise_prefix(text: str, rng: random.Random) -> str:
    prefixes = [
        "Partial crawl (2 of 5 sources failed): ",
        "Low-confidence excerpt — paywall on primary source: ",
        "Stale index fragment: ",
        "Unverified mirror copy: ",
    ]
    return rng.choice(prefixes) + text


def garble(snippet: str, completeness: float, query: str) -> tuple[str, float]:
    """Degrade an otherwise-good hit to simulate leaky search (blocked pages, OCR, truncation)."""
    rng = _rng(query)

    out = snippet
    if rng.random() < 0.85:
        out = _mask_prices(out, rng)
    if rng.random() < 0.75:
        out = _truncate(out, rng)
    if rng.random() < 0.45:
        out = _drop_clauses(out, rng)
    if rng.random() < 0.7:
        out = _add_noise_prefix(out, rng)

    # Pull completeness down; same query always gets same score (encourages retry loops).
    leak_completeness = completeness * rng.uniform(0.08, 0.22)
    leak_completeness = min(leak_completeness, 0.25)
    return out.strip(), round(leak_completeness, 3)

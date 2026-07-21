from __future__ import annotations

import re


def score_completeness(query: str, snippet: str, result_count: int) -> float:
    """Heuristic 0–1 score from query overlap, snippet length, and hit count."""
    terms = [t for t in re.split(r"\W+", query.lower()) if len(t) > 2]
    if not terms:
        terms = query.lower().split()

    text = snippet.lower()
    term_hits = sum(1 for t in terms if t in text) / max(len(terms), 1)
    length_score = min(len(snippet) / 500, 1.0)
    count_score = min(result_count / 3, 1.0)

    raw = 0.45 * term_hits + 0.35 * length_score + 0.2 * count_score
    return round(min(max(raw, 0.05), 0.95), 3)

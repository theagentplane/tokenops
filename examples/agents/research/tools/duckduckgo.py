from __future__ import annotations

import os

from examples.agents.research.tools.scoring import score_completeness


def duckduckgo_search(query: str, max_results: int = 5) -> tuple[str, float]:
    """Free web search via DuckDuckGo (ddgs package) — no API key required."""
    try:
        from ddgs import DDGS
    except ImportError as exc:
        raise RuntimeError("ddgs is not installed. Run: pip install ddgs") from exc

    timeout = int(os.environ.get("SEARCH_TIMEOUT", "20"))
    region = os.environ.get("SEARCH_REGION", "us-en")

    with DDGS(timeout=timeout) as ddgs:
        hits = list(ddgs.text(query, max_results=max_results, region=region))

    if not hits:
        raise RuntimeError(f"No web results for query: {query}")

    blocks: list[str] = []
    for hit in hits[:3]:
        title = hit.get("title") or "Untitled"
        body = hit.get("body") or ""
        href = hit.get("href") or ""
        blocks.append(f"**{title}**\n{body}\nSource: {href}")

    snippet = "\n\n".join(blocks)
    completeness = score_completeness(query, snippet, len(hits))
    return snippet, completeness

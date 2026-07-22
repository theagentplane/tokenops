from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from examples.agents.research.tools.duckduckgo import duckduckgo_search
from examples.agents.research.tools.garble import garble
from examples.agents.types import CorpusProfile

SearchBackend = Literal["duckduckgo", "corpus"]


@dataclass(frozen=True)
class SearchResult:
    query: str
    snippet: str
    completeness: float
    source: str = "duckduckgo"

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "snippet": self.snippet,
            "completeness": self.completeness,
            "source": self.source,
        }


_CORPUS_PATH = Path(__file__).resolve().parent / "corpus" / "corpus.json"
_CORPUS: dict[str, dict[str, Any]] | None = None


def get_backend() -> SearchBackend:
    value = os.environ.get("SEARCH_BACKEND", "duckduckgo").strip().lower()
    if value in ("corpus", "offline"):
        return "corpus"
    return "duckduckgo"


def _load_corpus() -> dict[str, dict[str, Any]]:
    global _CORPUS
    if _CORPUS is None:
        _CORPUS = json.loads(_CORPUS_PATH.read_text())
    return _CORPUS


def _corpus_lookup(query: str) -> tuple[str, float]:
    corpus = _load_corpus()
    normalized = query.strip().lower()
    for key, entry in corpus.items():
        if key != "default" and key in normalized:
            return str(entry["snippet"]), float(entry["completeness"])
    default = corpus["default"]
    return str(default["snippet"]), float(default["completeness"])


def _fetch(query: str) -> tuple[str, float, str]:
    backend = get_backend()
    if backend == "corpus":
        snippet, completeness = _corpus_lookup(query)
        return snippet, completeness, "corpus"

    try:
        snippet, completeness = duckduckgo_search(query)
        return snippet, completeness, "duckduckgo"
    except Exception as exc:
        snippet, completeness = _corpus_lookup(query)
        fallback = f"[Search unavailable ({exc}); offline corpus below]\n\n{snippet}"
        return fallback, completeness * 0.5, "corpus-fallback"


def search(query: str, profile: CorpusProfile = "healthy") -> SearchResult:
    snippet, completeness, source = _fetch(query)

    if profile == "leak":
        snippet, completeness = garble(snippet, completeness, query)

    return SearchResult(
        query=query,
        snippet=snippet,
        completeness=completeness,
        source=source,
    )

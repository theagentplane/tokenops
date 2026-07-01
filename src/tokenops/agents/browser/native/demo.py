"""Scripted 'brain' for the browser agent — a deterministic itinerary that walks into every
trap (huge DOM, recursive loop, trivial + hard task). The DOM is real, so token counts are
honest; only the decisions are canned, for a reproducible stage demo."""

from __future__ import annotations

import json

from tokenops.providers.types import ModelResponse

# Deliberately hits: /huge (giant DOM → compaction), a recursive p1↔p2 loop (loop guard),
# a trivial extract (route → cheap) and a dense page (route → strong).
DEFAULT_ITINERARY = [
    {"action": "navigate", "target": "/hard"},          # dense reasoning page (strong model)
    {"action": "navigate", "target": "/huge?rows=800"},  # giant DOM in context
    {"action": "navigate", "target": "/loop?p=1"},
    {"action": "click", "target": "next"},               # -> p2
    {"action": "click", "target": "next"},               # -> p1  (cycle begins)
    {"action": "click", "target": "next"},               # -> p2
    {"action": "click", "target": "next"},               # -> p1  (clearly looping)
    {"action": "navigate", "target": "/easy"},           # trivial (cheap model)
    {"action": "extract", "target": "phone"},
    {"action": "finish"},
]


def demo_browser_complete(itinerary=None):
    """Return a ``complete(provider, model, messages, ...)`` that pops the next canned
    decision. Input tokens track the real message length so a huge DOM costs real tokens."""
    itin = list(itinerary or DEFAULT_ITINERARY)
    state = {"n": 0}

    def complete(provider, model, messages, max_output_tokens=None, **kwargs):
        i = state["n"]
        state["n"] += 1
        decision = itin[i] if i < len(itin) else {"action": "finish"}
        input_tokens = max(1, len(str(messages)) // 4)  # real DOM → real token count
        return ModelResponse(content=json.dumps(decision), input_tokens=input_tokens, output_tokens=20)

    return complete

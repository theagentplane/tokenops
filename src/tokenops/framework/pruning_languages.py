"""The language handlers tool-output pruning knows, and how a ``languages`` setting picks among them."""

from __future__ import annotations

from collections.abc import Sequence

from tokenops.framework.pruning_c import CHandler
from tokenops.framework.pruning_go import GoHandler
from tokenops.framework.pruning_java import JavaHandler
from tokenops.framework.pruning_python import PythonHandler
from tokenops.framework.pruning_rust import RustHandler
from tokenops.framework.pruning_types import LanguageHandler

HANDLERS: dict[str, LanguageHandler] = {
    h.name: h for h in (PythonHandler(), GoHandler(), JavaHandler(), RustHandler(), CHandler())
}
ALIASES = {"cpp": "c", "c++": "c", "golang": "go", "py": "python", "rs": "rust"}


def resolve_languages(spec: str | Sequence[str]) -> tuple[LanguageHandler, ...]:
    """Handlers for `spec`: ``"auto"`` (every handler) or a list of language names. Unknown names raise ValueError."""
    if isinstance(spec, str):
        spec = [spec]
    chosen: dict[str, LanguageHandler] = {}
    for raw in spec:
        key = raw.strip().lower()
        if key == "auto":
            return tuple(HANDLERS.values())
        key = ALIASES.get(key, key)
        if key not in HANDLERS:
            known = ", ".join(sorted(HANDLERS))
            raise ValueError(f"tool_output_prune: unknown language {raw!r} (known: {known}, auto)")
        chosen[key] = HANDLERS[key]
    if not chosen:
        raise ValueError("tool_output_prune: `languages` must name at least one language")
    return tuple(chosen.values())

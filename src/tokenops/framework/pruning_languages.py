"""The language handlers tool-output pruning knows, and how a ``languages`` setting picks among them."""

from __future__ import annotations

from collections.abc import Sequence

from tokenops.framework.pruning_c import CHandler
from tokenops.framework.pruning_go import GoHandler
from tokenops.framework.pruning_java import JavaHandler
from tokenops.framework.pruning_js import JsHandler
from tokenops.framework.pruning_python import PythonHandler
from tokenops.framework.pruning_rust import RustHandler
from tokenops.framework.pruning_shell import ShellHandler
from tokenops.framework.pruning_sql import SqlHandler
from tokenops.framework.pruning_types import LanguageHandler

HANDLERS: dict[str, LanguageHandler] = {
    h.name: h
    for h in (
        PythonHandler(),
        GoHandler(),
        JavaHandler(),
        RustHandler(),
        CHandler(),
        JsHandler(),
        ShellHandler(),
        SqlHandler(),
    )
}
ALIASES = {
    "cpp": "c",
    "c++": "c",
    "golang": "go",
    "py": "python",
    "rs": "rust",
    "javascript": "js",
    "typescript": "js",
    "ts": "js",
    "node": "js",
    "sh": "shell",
    "bash": "shell",
    "zsh": "shell",
}
# `"auto"` leaves these out: their text cannot be told from other text by a window alone (a shell window can start
# inside a heredoc body). Enable them by name.
AUTO_EXCLUDED = frozenset({"shell"})


def resolve_languages(
    spec: str | Sequence[str], *, keep_jsdoc_types: bool = True
) -> tuple[LanguageHandler, ...]:
    """Handlers for `spec`: ``"auto"`` (every handler not in ``AUTO_EXCLUDED``) or a list of names. Unknown names raise ValueError.

    `keep_jsdoc_types` is passed to the JS/TS handler (JSDoc blocks with type tags stay when true)."""
    if isinstance(spec, str):
        spec = [spec]
    chosen: dict[str, LanguageHandler] = {}
    for raw in spec:
        key = raw.strip().lower()
        if key == "auto":
            return tuple(_handler(k, keep_jsdoc_types) for k in HANDLERS if k not in AUTO_EXCLUDED)
        key = ALIASES.get(key, key)
        if key not in HANDLERS:
            known = ", ".join(sorted(HANDLERS))
            raise ValueError(f"tool_output_prune: unknown language {raw!r} (known: {known}, auto)")
        chosen[key] = _handler(key, keep_jsdoc_types)
    if not chosen:
        raise ValueError("tool_output_prune: `languages` must name at least one language")
    return tuple(chosen.values())


def _handler(name: str, keep_jsdoc_types: bool) -> LanguageHandler:
    return HANDLERS[name] if name != "js" or keep_jsdoc_types else JsHandler(keep_jsdoc_types=False)

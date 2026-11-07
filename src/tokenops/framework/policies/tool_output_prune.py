"""tool_output_prune — hide what a coding agent rarely needs from a tool result, before the cap measures it.

LLD row:
    Detect: the tool result text is a block of source code in an enabled language (Python by default; Go, Java, Rust,
            C/C++ on request): clean lexing, that language's structure, not a diff, grep hit list or test report.
    Fix:    SHAPE — replace the result the agent sees by the same text with comments and docstrings hidden. Code
            lines stay verbatim and the line count is unchanged (hidden blocks become blank lines), so exact-text
            edits and cited line numbers still hold. Never HALT, never drops code, no model, no tokenizer.

Unlike ``tool_output_cap`` this does not wait for a result to be large: it shapes a result of any size, and it runs
*before* the cap so the cap measures what the agent will actually receive. The shaped text is handed to the host
through ``controls.take_shaped_result()``; a host that does not call it is unaffected. It works from the result text
alone (the command is not needed), so it only prunes text it can prove is source code in an enabled language, and refuses when two languages score close.
"""

from __future__ import annotations

from collections.abc import Sequence

from tokenops.framework.core import Action, ActionKind, Detector, LedgerView, Policy, Signal
from tokenops.framework.pruning import prune_any
from tokenops.framework.pruning_languages import resolve_languages


class ToolOutputPruneDetector(Detector):
    """Shapes a tool result; raises no signals (the saving is reported through the controls)."""

    name = "tool_output_prune"

    def __init__(
        self,
        *,
        comments: bool = True,
        docstrings: bool = True,
        min_saved_chars: int = 200,
        languages: str | Sequence[str] = ("python",),
        keep_jsdoc_types: bool = True,
    ) -> None:
        self.handlers = resolve_languages(languages, keep_jsdoc_types=keep_jsdoc_types)
        self.comments = comments
        self.docstrings = docstrings
        self.min_saved_chars = min_saved_chars

    def shape_tool_result(self, boundary_id: str, text: str) -> str | None:
        return prune_any(
            text,
            self.handlers,
            comments=self.comments,
            docstrings=self.docstrings,
            min_saved_chars=self.min_saved_chars,
        )


class ToolOutputPrunePolicy(Policy):
    """Nothing to decide: the detector shapes the result itself. Kept so the template registers like the others."""

    name = "tool_output_prune"

    def decide(self, signal: Signal, view: LedgerView) -> Action:
        return Action(kind=ActionKind.ALLOW, trace_id=signal.trace_id, reason=signal.reason)


def build(
    *,
    comments: bool = True,
    docstrings: bool = True,
    min_saved_chars: int = 200,
    languages: str | Sequence[str] = ("python",),
    keep_jsdoc_types: bool = True,
) -> tuple[Detector, Policy]:
    return (
        ToolOutputPruneDetector(
            comments=comments,
            docstrings=docstrings,
            min_saved_chars=min_saved_chars,
            languages=languages,
            keep_jsdoc_types=keep_jsdoc_types,
        ),
        ToolOutputPrunePolicy(),
    )

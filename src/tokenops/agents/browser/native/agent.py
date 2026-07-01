"""Native browser agent — observe (snapshot) → decide (model) → act (tool) loop.

Governance is automatic: the model call goes through the injected ``complete_fn``
(``wrap_complete`` observes it and applies routing/caching/compaction), and each browser
action is a Chronicle ``@boundary`` (observed as a tool crossing → loop guard, tool caps).
The model "brain" is scripted for the demo; the DOM it reads is real, so token counts —
and therefore the caching/compaction deltas — are honest.
"""

from __future__ import annotations

import json
import re
from typing import Callable

from tokenops.agents.browser.native.tools import BrowserBackend, HttpxBrowser
from tokenops.agents.types import StepCallback, StepEvent, TokenUsage
from tokenops.chronicle import boundary
from tokenops.chronicle.schema import InputState
from tokenops.config.schema import AgentServerConfig
from tokenops.providers import complete

# Stable system prefix (tools + instructions). Kept constant across steps so a prompt cache
# can reuse it — the volatile page snapshot goes in the user message.
SYSTEM_PROMPT = (
    "You are a browser automation agent. Tools: navigate(url), click(id), extract(id), finish. "
    "Reply with JSON only: {\"action\": <tool>, \"target\": <arg>}. "
    "Use the page snapshot to decide the next single action toward the task."
)


def _parse(content: str) -> dict:
    try:
        return json.loads(content.strip())
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", content, re.DOTALL)
        return json.loads(m.group()) if m else {"action": "finish"}


def _make_tools(backend: BrowserBackend, on_step: StepCallback | None):
    """Return @boundary-wrapped browser actions. Each returns the resulting URL/value as the
    result, so the ledger's tool crossing carries the visited state (for cycle detection)."""

    def _emit(action: str, target: str, detail: str) -> None:
        if on_step:
            on_step(StepEvent(agent="browser", action=action, query=target, detail=detail))  # type: ignore[arg-type]

    @boundary("navigate", kind="tool",
              extract_input=lambda url: InputState(graph_state={"name": "navigate", "args": {"url": url}}))
    def navigate(url: str) -> str:
        u = backend.navigate(url); _emit("navigate", url, u); return u

    @boundary("click", kind="tool",
              extract_input=lambda element_id: InputState(graph_state={"name": "click", "args": {"id": element_id}}))
    def click(element_id: str) -> str:
        u = backend.click(element_id); _emit("click", element_id, u); return u

    @boundary("extract", kind="tool",
              extract_input=lambda element_id: InputState(graph_state={"name": "extract", "args": {"id": element_id}}))
    def extract(element_id: str) -> str:
        v = backend.extract(element_id); _emit("extract", element_id, v); return v

    return {"navigate": navigate, "click": click, "extract": extract}


class NativeBrowserAgent:
    def __init__(self, config: AgentServerConfig) -> None:
        self._config = config

    def run(
        self,
        task: str,
        on_step: StepCallback | None = None,
        complete_fn=None,
        *,
        backend: BrowserBackend | None = None,
        service: str = "browser",
    ) -> str:
        cfg = self._config
        do_complete = complete_fn or complete
        backend = backend or HttpxBrowser()
        tools = _make_tools(backend, on_step)
        extracted: list[str] = []

        for step in range(1, cfg.max_steps + 1):
            snapshot = backend.snapshot()
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},  # stable → cacheable prefix
                {"role": "user", "content": f"URL: {backend.current_url}\nTASK: {task}\n\nPAGE:\n{snapshot}"},
            ]
            response = do_complete(cfg.provider, cfg.model, messages)
            if on_step:
                on_step(StepEvent(agent="browser", action="model", detail="decision",  # type: ignore[arg-type]
                                  tokens=TokenUsage(response.input_tokens, response.output_tokens)))

            decision = _parse(response.content)
            action = decision.get("action", "finish")
            if action == "finish":
                break
            target = str(decision.get("target", ""))
            if action in tools:
                result = tools[action](target)
                if action == "extract":
                    extracted.append(result)

        return " | ".join(extracted) if extracted else f"visited {backend.current_url}"

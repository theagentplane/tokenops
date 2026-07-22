"""Benchmark Role factory for live MetaGPT runs."""

from __future__ import annotations

import os


def _api_key() -> str:
    key = os.getenv("OPENAI_API_KEY") or os.getenv("METAGPT_API_KEY")
    if not key:
        raise RuntimeError("Set OPENAI_API_KEY in .env for live MetaGPT benchmarks")
    return key


def make_bench_role(*, max_react_loop: int = 5, model: str | None = None):
    """Return a fresh react-mode Role with a single Research action."""
    from metagpt.actions import Action
    from metagpt.config2 import Config
    from metagpt.context import Context
    from metagpt.roles.role import Role, RoleReactMode

    chosen = model or os.getenv("METAGPT_BENCH_MODEL", "gpt-4o-mini")
    config = Config.from_llm_config({
        "api_type": "openai",
        "api_key": _api_key(),
        "model": chosen,
        "base_url": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
    })
    ctx = Context(config=config)

    class Research(Action):
        name: str = "Research"

        async def run(self, instruction: str):
            prompt = (
                f"{instruction}\n\n"
                "Give a concise factual bullet summary (3-6 bullets). "
                "If the user task is complete, end with DONE on its own line."
            )
            return await self._aask(prompt)

    class BenchRole(Role):
        name: str = "Researcher"
        profile: str = "Market researcher"

        def __init__(self, **kwargs):
            super().__init__(context=ctx, **kwargs)
            # Single action avoids MetaGPT multi-state -1 → None todo crash in _act.
            self.set_actions([Research])
            self._set_react_mode(RoleReactMode.REACT.value, max_react_loop=max_react_loop)

    return BenchRole()

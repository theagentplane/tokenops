"""Three-agent TokenOps demo: Scout → Analyst → Editor (LangChain).

Agent logic uses LangChain ``ChatOpenAI`` / ``StructuredTool``. TokenOps seams
live in each ``server.py``: entry/downstream scope, ``wrap_complete`` over a
LangChain dispatch, ``GovernedChatModel``, ``@boundary`` tools, crossing hook.
"""

from examples.brief.client import submit_brief_sync, submit_brief_sync_with_meta

__all__ = ["submit_brief_sync", "submit_brief_sync_with_meta"]

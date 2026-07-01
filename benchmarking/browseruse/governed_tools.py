"""Bridge browser-use ``Tools.act`` into TokenOps observations."""

from __future__ import annotations

from functools import wraps

from tokenops.control.boundary import emit_observation, observation_from_crossing
from tokenops.control.context import current_governance, current_registration

from benchmarking.browseruse.session import current_active_run


def _action_label(action) -> str:
    for attr in ("action", "name", "action_name"):
        val = getattr(action, attr, None)
        if val:
            return str(val)
    return type(action).__name__


def make_governed_act(orig_act):
    @wraps(orig_act)
    async def governed_act(self, action, browser_session, *args, **kwargs):
        if current_active_run() is None or current_governance() is None:
            return await orig_act(self, action, browser_session, *args, **kwargs)
        result = await orig_act(self, action, browser_session, *args, **kwargs)
        if current_registration() is not None:
            emit_observation(
                observation_from_crossing(
                    boundary_id=f"browseruse.tool.{_action_label(action)}",
                    kind="tool",
                    service="browseruse",
                    input_state={"action": _action_label(action)},
                    result=result,
                )
            )
        return result

    return governed_act

"""Attribution builders (internal).

Integrators use :func:`~tokenops.capabilities.run.tokenops_run` —
not these helpers directly. Boundaries call :func:`require_hop`.
"""

from __future__ import annotations

from collections.abc import Mapping

from tokenops.framework.context import current_hop
from tokenops.framework.core import Attribution
from tokenops.framework.models import HopAttribution, NoGovernanceScopeError

# Payload keys allowed to merge into user_dims when the agent owns intent/mode (§1).
_PAYLOAD_USER_DIM_ALLOWLIST = frozenset({"user_id", "user"})


def _coerce_user_dims(raw: object) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items()}


def merge_hop_dims(
    agent_dims: Mapping[str, str] | None,
    payload: Mapping[str, object] | None,
) -> dict[str, str]:
    """Agent ``user_dims`` first; allow-listed client keys fill gaps only."""
    dims = {str(k): str(v) for k, v in (agent_dims or {}).items()}
    body = dict(payload or {})
    payload_dims = _coerce_user_dims(body.get("user_dims"))
    for key in _PAYLOAD_USER_DIM_ALLOWLIST:
        if key in dims:
            continue
        if key in payload_dims:
            dims[key] = payload_dims[key]
        elif key in body and body[key] is not None and str(body[key]).strip():
            dims[key] = str(body[key])
    return dims


def _build_attribution(reg: HopAttribution, *, service: str) -> Attribution:
    """Map the hop attribution + boundary ``service`` to ledger/policy ``Attribution``."""
    tags = dict(reg.user_dims)
    if reg.intent:
        tags.setdefault("intent", reg.intent)
    user = reg.user_dims.get("user_id", reg.user_dims.get("user", "unknown"))
    return Attribution(user=user, agent=service, trace_id=reg.trace_id, tags=tags)


def require_hop() -> HopAttribution:
    """Fail closed when boundaries run outside a bound request context."""
    reg = current_hop()
    if reg is None:
        raise NoGovernanceScopeError(
            "no governed scope in this context: wrap the work in tokenops_run"
        )
    return reg


# Deprecated names kept for 1.x.
require_registration = require_hop
merge_registration_dims = merge_hop_dims

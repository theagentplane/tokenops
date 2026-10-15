"""HTTP mapping of governance outcomes for agent apps.

A ``Halt`` becomes a ``200`` ``halted`` body and a ``Throttled`` a ``429`` with
``Retry-After``, so an agent's task endpoint does not surface them as a ``500``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from fastapi.responses import JSONResponse, Response

from tokenops.framework.core import Halt
from tokenops.framework.engine import Throttled

Handler = Callable[[dict[str, Any], Mapping[str, str]], Awaitable[dict[str, Any] | Response]]


def with_governance_errors(handler: Handler) -> Handler:
    """Wrap a task handler so Halt -> 200 halted and Throttled -> 429."""

    async def wrapped(
        payload: dict[str, Any],
        headers: Mapping[str, str],
    ) -> dict[str, Any] | Response:
        try:
            return await handler(payload, headers)
        except Halt as halt:
            return JSONResponse(
                {"status": "halted", "reason": halt.action.reason},
                status_code=200,
            )
        except Throttled as thr:
            retry_after = str(int(thr.action.retry_after_s or 1))
            return JSONResponse(
                {"status": "throttled", "reason": thr.action.reason},
                status_code=429,
                headers={"Retry-After": retry_after},
            )

    return wrapped

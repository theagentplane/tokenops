"""TokenOps: run-aware token governance for agents."""

from tokenops.env import load_env

load_env()

from tokenops._version import __version__


def init() -> None:
    """Process bootstrap: install the Chronicle crossing hook (idempotent).

    Prefer calling this (or :meth:`ControlPlaneClient.from_env` /
    :func:`~tokenops.interfaces.instrument.instrument_app`) on agent startup so
    callers need not remember :func:`~tokenops.capabilities.crossing.install_crossing_hook`.
    """
    from tokenops.capabilities.crossing import install_crossing_hook

    install_crossing_hook()


# First-class SDK surface for agents / UIs talking to the plane.
from tokenops.capabilities.ledger_writers import flush_ledger_writes as flush_ledger_writes
from tokenops.capabilities.run import (
    TokenOpsBound as TokenOpsBound,
)
from tokenops.capabilities.run import (
    agentplane_run_scope as agentplane_run_scope,
)
from tokenops.capabilities.run import (
    tokenops_run as tokenops_run,
)
from tokenops.framework.request_context import (
    RequestContext as RequestContext,
)
from tokenops.framework.request_context import (
    bind_request_context as bind_request_context,
)
from tokenops.framework.request_context import (
    clear_request_context as clear_request_context,
)
from tokenops.framework.request_context import (
    current_request_context as current_request_context,
)
from tokenops.interfaces.instrument import instrument_app as instrument_app
from tokenops.repositories import ControlPlaneClient as ControlPlaneClient

__all__ = [
    "ControlPlaneClient",
    "RequestContext",
    "TokenOpsBound",
    "agentplane_run_scope",
    "bind_request_context",
    "clear_request_context",
    "current_request_context",
    "flush_ledger_writes",
    "init",
    "instrument_app",
    "tokenops_run",
    "__version__",
]

"""TokenOps control plane and SDK."""

from tokenops.env import load_env

load_env()

__version__ = "0.1.0"


def init() -> None:
    """Process bootstrap: install the Chronicle crossing hook (idempotent).

    Prefer calling this (or :meth:`ControlPlaneClient.from_env` /
    :func:`~tokenops.control.instrument.instrument_app`) on agent startup so
    callers need not remember :func:`~tokenops.control.crossing.install_crossing_hook`.
    """
    from tokenops.control.crossing import install_crossing_hook

    install_crossing_hook()


# First-class SDK surface for agents / UIs talking to the plane.
from tokenops.control.client import ControlPlaneClient as ControlPlaneClient
from tokenops.control.instrument import instrument_app as instrument_app
from tokenops.control.request_context import (
    RequestContext as RequestContext,
)
from tokenops.control.request_context import (
    bind_request_context as bind_request_context,
)
from tokenops.control.request_context import (
    clear_request_context as clear_request_context,
)
from tokenops.control.request_context import (
    current_request_context as current_request_context,
)
from tokenops.control.run import (
    TokenOpsBound as TokenOpsBound,
)
from tokenops.control.run import (
    agentplane_run_scope as agentplane_run_scope,
)
from tokenops.control.run import (
    tokenops_run as tokenops_run,
)

__all__ = [
    "ControlPlaneClient",
    "RequestContext",
    "TokenOpsBound",
    "agentplane_run_scope",
    "bind_request_context",
    "clear_request_context",
    "current_request_context",
    "init",
    "instrument_app",
    "tokenops_run",
    "__version__",
]

"""Errors raised by the control-plane client.

Only I/O failures and refusals are represented here; what to do about them (fail open or
closed) is decided by the caller, never by the client.
"""

from __future__ import annotations


class ControlPlaneError(Exception):
    """The control plane answered, but not with success (a ``4xx`` or ``5xx``)."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ControlPlaneUnavailable(ControlPlaneError):
    """The control plane could not be reached, or did not answer in time."""

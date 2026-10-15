"""One background ledger writer per control-plane client, shared by every hop in a process.

``tokenops_run`` asks :func:`writer_for` for the writer of its client, so all runs of a
process share one queue and one thread. :func:`flush_ledger_writes` drains them (it also runs
at interpreter exit), so a short script does not lose its last spend.
"""

from __future__ import annotations

import atexit
import threading

from tokenops.repositories import ControlPlaneClient, LedgerEventWriter

_LOCK = threading.Lock()
# Keeps the client referenced so its id() cannot be reused while its writer is alive.
_WRITERS: dict[int, tuple[ControlPlaneClient, LedgerEventWriter]] = {}
_ATEXIT_REGISTERED = False


def writer_for(client: ControlPlaneClient) -> LedgerEventWriter:
    """The shared writer for ``client`` (created on first use)."""
    global _ATEXIT_REGISTERED
    with _LOCK:
        entry = _WRITERS.get(id(client))
        if entry is None:
            entry = (client, LedgerEventWriter(client))
            _WRITERS[id(client)] = entry
            if not _ATEXIT_REGISTERED:
                atexit.register(flush_ledger_writes)
                _ATEXIT_REGISTERED = True
        return entry[1]


def flush_ledger_writes(timeout: float = 5.0) -> bool:
    """Wait until every queued ledger event has been sent or dropped (``False`` on timeout)."""
    with _LOCK:
        writers = [w for _, w in _WRITERS.values()]
    return all([w.flush(timeout) for w in writers])

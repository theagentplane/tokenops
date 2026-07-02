"""In-process background drain for trajectory index build queue."""

from __future__ import annotations

import threading

from tokenops.control.store import Store

_drain_lock = threading.Lock()


def schedule_trajectory_drain(
    store: Store,
    *,
    limit: int = 8,
    max_age_days: int = 30,
    max_entries_per_scope: int = 500,
) -> None:
    """Fire-and-forget drain of the trajectory build queue in a daemon thread."""

    def _run() -> None:
        with _drain_lock:
            store.drain_trajectory_build_queue(
                limit=limit,
                max_age_days=max_age_days,
                max_entries_per_scope=max_entries_per_scope,
            )

    threading.Thread(target=_run, daemon=True, name="trajectory-index-drain").start()

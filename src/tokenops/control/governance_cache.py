"""Thread-safe, deep-copying governance-config cache.

Local Stores cache until an explicit invalidation. HTTP clients additionally use a
lazy soft/hard TTL: soft expiry returns the last known-good config and refreshes it
on a daemon thread; hard expiry refreshes synchronously and fails closed if that
refresh fails. Governors are never cached — only their input config is.
"""

from __future__ import annotations

import copy
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class _Entry:
    config: dict
    fetched_at: float
    refreshing: bool = False


_LOCK = threading.Lock()
_CACHE: dict[tuple[str, str], _Entry] = {}


def clear_governance_config_cache(
    *, agent: str | None = None, store_path: str | None = None
) -> None:
    """Drop cached configs, optionally narrowed to one cache key and/or agent."""
    with _LOCK:
        keys = [
            key
            for key in _CACHE
            if (store_path is None or key[0] == store_path) and (agent is None or key[1] == agent)
        ]
        for key in keys:
            del _CACHE[key]


def _store(key: tuple[str, str], config: dict, now: float) -> dict:
    with _LOCK:
        _CACHE[key] = _Entry(config=copy.deepcopy(config), fetched_at=now)
        return copy.deepcopy(_CACHE[key].config)


def _refresh(key: tuple[str, str], loader: Callable[[], dict], clock: Callable[[], float]) -> None:
    try:
        _store(key, loader(), clock())
    finally:
        with _LOCK:
            entry = _CACHE.get(key)
            if entry is not None:
                entry.refreshing = False


def get_cached_governance_config(
    store_path: str,
    agent: str,
    loader: Callable[[], dict],
    *,
    soft_ttl_s: float | None = None,
    hard_ttl_s: float | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> dict:
    """Load a config, returning an independent copy on every call.

    ``None`` TTLs retain the Store's historic explicit-invalidation behavior. For
    HTTP callers, ``0 <= soft <= hard`` gives a bounded-staleness cache.
    """
    if (soft_ttl_s is None) != (hard_ttl_s is None):
        raise ValueError("soft_ttl_s and hard_ttl_s must be set together")
    if soft_ttl_s is not None and (soft_ttl_s < 0 or hard_ttl_s is None or hard_ttl_s < soft_ttl_s):
        raise ValueError("expected 0 <= soft_ttl_s <= hard_ttl_s")
    if soft_ttl_s is not None:
        assert hard_ttl_s is not None
    hard_ttl = hard_ttl_s

    key = (store_path, agent)
    now = clock()
    with _LOCK:
        entry = _CACHE.get(key)
        if entry is not None and soft_ttl_s is None:
            return copy.deepcopy(entry.config)
        if entry is not None:
            assert soft_ttl_s is not None
            age = now - entry.fetched_at
            if age < soft_ttl_s:
                return copy.deepcopy(entry.config)
            assert hard_ttl is not None
            if age < hard_ttl:
                if not entry.refreshing:
                    entry.refreshing = True
                    threading.Thread(
                        target=_refresh, args=(key, loader, clock), daemon=True
                    ).start()
                return copy.deepcopy(entry.config)

    # Initial and hard-expired fetches block. A failure deliberately propagates:
    # constructing a governor from unknown config would be an unenforced run.
    return _store(key, loader(), clock())


def governance_config_cache_size() -> int:
    with _LOCK:
        return len(_CACHE)

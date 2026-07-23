"""Process-level cache for governance config dicts (design notes §10).

Caches the dict returned by ``governance_config_for`` only — not Governor
instances. Callers still ``build_governor`` fresh per run from a cached copy.

Key: ``(store_path, agent)``. Invalidate via :func:`clear_governance_config_cache`
or automatically on Store governance writes (seed / upsert / delete).

Thread-safe: get / set / invalidate are serialized on a process-wide Lock. Loaders run
*outside* the lock so Store DB work cannot deadlock with invalidation. Concurrent misses
may invoke the loader more than once; the first writer wins and callers always receive
an independent deep copy. See ``docs/concurrency.md``.
"""

from __future__ import annotations

import copy
import threading
from typing import Callable

_LOCK = threading.Lock()
_CACHE: dict[tuple[str, str], dict] = {}


def clear_governance_config_cache(
    *,
    agent: str | None = None,
    store_path: str | None = None,
) -> None:
    """Drop cached governance configs.

    * No args → clear entire process cache.
    * ``store_path`` only → clear all agents for that DB.
    * ``agent`` only → clear that agent across all DBs.
    * Both → clear that agent for that DB.
    """
    with _LOCK:
        if agent is None and store_path is None:
            _CACHE.clear()
            return
        to_drop = [
            key
            for key in _CACHE
            if (store_path is None or key[0] == store_path)
            and (agent is None or key[1] == agent)
        ]
        for key in to_drop:
            del _CACHE[key]


def get_cached_governance_config(
    store_path: str,
    agent: str,
    loader: Callable[[], dict],
) -> dict:
    """Return a deep copy of the cached config, loading via ``loader`` on miss."""
    key = (store_path, agent)
    with _LOCK:
        hit = _CACHE.get(key)
        if hit is not None:
            return copy.deepcopy(hit)
    cfg = loader()
    with _LOCK:
        # Another thread may have filled it; prefer first writer, still return a copy.
        existing = _CACHE.get(key)
        if existing is None:
            _CACHE[key] = copy.deepcopy(cfg)
            return copy.deepcopy(_CACHE[key])
        return copy.deepcopy(existing)


def governance_config_cache_size() -> int:
    """Test helper: number of entries currently cached."""
    with _LOCK:
        return len(_CACHE)

"""Cache affinity: send a per-run routing hint so one agent run reaches one backend replica.

A provider's prompt cache lives on the replica that served an earlier call, so a run whose calls
are spread over replicas loses the cache discount. How the hint is expressed differs per
provider (a body field, a header, or nothing), so it sits behind a small strategy.

This is a transport setting: it never touches ``messages``, ``model`` or sampling, and it works
with governance off. It is off unless the caller turns it on (``mode: "auto"`` or an explicit
strategy).
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

__all__ = [
    "AffinityRun",
    "BodyField",
    "CacheAffinity",
    "Header",
    "NoAffinity",
    "affinity_for",
    "open_affinity_run",
    "run_key",
]


class CacheAffinity(Protocol):
    @property
    def name(self) -> str:
        """Strategy name, ``none`` when no hint is sent."""

    def apply(self, kwargs: dict[str, Any], key: str) -> dict[str, Any]:
        """Return a COPY of the dispatch kwargs carrying the routing hint. Never mutate."""

    def rejects(self, exc: BaseException) -> bool:
        """True if this provider error is about the hint itself (so it may be re-sent without)."""


@dataclass(frozen=True)
class BodyField:
    """OpenAI / Azure OpenAI: a field in the request body, sent through ``extra_body``."""

    field: str = "prompt_cache_key"
    name: str = "body_field"

    def apply(self, kwargs: dict[str, Any], key: str) -> dict[str, Any]:
        extra = dict(kwargs.get("extra_body") or {})
        extra[self.field] = key
        return {**kwargs, "extra_body": extra}

    def rejects(self, exc: BaseException) -> bool:
        return self.field in str(exc)


@dataclass(frozen=True)
class Header:
    """A request header that pins a conversation to a server (via ``extra_headers``)."""

    header: str
    name: str = "header"

    def apply(self, kwargs: dict[str, Any], key: str) -> dict[str, Any]:
        headers = dict(kwargs.get("extra_headers") or {})
        headers[self.header] = key
        return {**kwargs, "extra_headers": headers}

    def rejects(self, exc: BaseException) -> bool:
        return self.header.lower() in str(exc).lower()


class NoAffinity:
    """No routing hint: the provider has no key, or the setting is off."""

    name = "none"

    def apply(self, kwargs: dict[str, Any], key: str) -> dict[str, Any]:
        return kwargs

    def rejects(self, exc: BaseException) -> bool:
        return False


# Only providers confirmed in their docs or by a probe. Anything else (Anthropic, Bedrock,
# Gemini, xAI, Fireworks, DeepSeek, local servers) resolves to NoAffinity under ``auto``; use an
# explicit ``{"header": ...}`` / ``{"body_field": ...}`` mode for those until a row is verified.
_REGISTRY: dict[str, CacheAffinity] = {
    "openai": BodyField(),
    "azure": BodyField(),
}


def affinity_for(provider: str) -> CacheAffinity:
    return _REGISTRY.get(provider.split("/")[0].lower(), NoAffinity())


def run_key(trace_id: str) -> str:
    """One key per agent run: constant across the run's calls, different between runs."""
    return "tokenops-" + hashlib.sha256(trace_id.encode()).hexdigest()[:12]


def _resolve_strategy(mode: Any, provider: str) -> CacheAffinity:
    if mode in (None, False, "off"):
        return NoAffinity()
    if mode == "auto":
        return affinity_for(provider)
    if isinstance(mode, Mapping) and len(mode) == 1:
        ((kind, value),) = mode.items()
        if kind == "body_field" and isinstance(value, str) and value:
            return BodyField(value)
        if kind == "header" and isinstance(value, str) and value:
            return Header(value)
    raise ValueError(
        f"cache_affinity mode {mode!r} is not 'off', 'auto', {{'body_field': <name>}} "
        "or {'header': <name>}"
    )


def _resolve_key(spec: Any, trace_id: str) -> str:
    if spec in (None, "run"):
        return run_key(trace_id)
    if isinstance(spec, str) and spec.startswith("fixed:") and len(spec) > len("fixed:"):
        return spec[len("fixed:") :]
    raise ValueError(f"cache_affinity key {spec!r} is not 'run' or 'fixed:<string>'")


class AffinityRun:
    """Per-run state: the strategy, the run's key, and whether the hint is still being sent."""

    def __init__(self, strategy: CacheAffinity, key: str) -> None:
        self.strategy = strategy
        self.key = key
        #: ``off`` (nothing to send), ``sent`` or ``refused`` (provider rejected it, now off).
        self.status = "sent" if strategy.name != "none" else "off"

    def call(self, send: Callable[..., Any], kwargs: dict[str, Any]) -> Any:
        """``send(**kwargs)``, with the hint applied. If the provider refuses the hint, re-send
        once without it and stay unkeyed for the rest of the run. Other errors are raised."""
        if self.status == "sent":
            try:
                return send(**self.strategy.apply(kwargs, self.key))
            except Exception as exc:
                if not self.strategy.rejects(exc):
                    raise
                self.status = "refused"
        return send(**kwargs)

    def metadata(self) -> dict[str, str]:
        """Envelope metadata; empty when affinity is off, so default envelopes are unchanged."""
        return {} if self.status == "off" else {"tokenops.cache_affinity": self.status}


def open_affinity_run(config: Any, provider: str, trace_id: str) -> AffinityRun:
    """Resolve ``config`` (``None``, ``"auto"``, or ``{"mode": ..., "key": ...}``) for a run."""
    if isinstance(config, Mapping):
        unknown = set(config) - {"mode", "key"}
        if unknown:
            raise ValueError(f"unknown cache_affinity keys {sorted(unknown)}")
        mode, key = config.get("mode"), config.get("key")
    else:
        mode, key = config, None
    return AffinityRun(_resolve_strategy(mode, provider), _resolve_key(key, trace_id))

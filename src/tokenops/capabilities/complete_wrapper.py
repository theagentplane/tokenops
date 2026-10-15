"""``wrap_complete``: govern a ``complete(provider, model, messages)`` entry point.

Pre-call governance (MUTATE / HALT / RETRY) happens here; the dispatch itself goes through
Chronicle ``wrap_llm`` so the LIVE record and ``on_crossing`` fire. The TokenOps crossing hook
projects crossings into ``Governor.observe``: do not also ``emit_observation`` here, or the
call is billed twice.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from chronicle import wrap_llm

from tokenops.capabilities.crossing import (
    install_crossing_hook,
    reset_wrap_owns_precall,
    wrap_owns_precall,
)
from tokenops.framework.core import Attribution, CallRequest
from tokenops.framework.engine import ApplyControls, Governor
from tokenops.framework.message_steering import (
    compact_messages,
    consume_carry,
    estimate_input_tokens,
)

__all__ = ["DispatchFn", "policy_metadata", "tighten_cap", "wrap_complete"]

#: A dispatch callable: (provider, model, messages, max_output_tokens) -> response.
DispatchFn = Callable[..., object]

_RETRY_BASE_CAP = 512


def tighten_cap(cap: int | None) -> int:
    """RETRY tightens the output cap each attempt (halve, floor 64)."""
    return max(64, (cap or _RETRY_BASE_CAP) // 2)


def policy_metadata(controls: ApplyControls) -> Callable[[object], dict[str, int]]:
    """Envelope metadata for what a policy did to this call.

    The plane stores no per-policy statistics (control-plane ADR 0009), so what a policy
    achieved is recorded on the envelope instead: ``tokenops.compaction_tokens_before``,
    ``..._tokens_after`` and ``..._tokens_saved`` when ``context_compaction`` rewrote the
    prompt. Read after the dispatch returns, so ``controls.call`` is this call's.
    """

    def extract(_result: object) -> dict[str, int]:
        call = getattr(controls, "call", None)
        compaction = getattr(call, "compaction", None) if call is not None else None
        if not compaction:
            return {}
        return {f"tokenops.compaction_{key}": int(value) for key, value in compaction.items()}

    return extract


def wrap_complete(
    governor: Governor,
    controls: ApplyControls,
    attr: Attribution,
    *,
    provider: str,
    model: str,
    dispatch: DispatchFn,
    est_input_fn: Callable[[object], int] | None = None,
    service: str = "",
    max_call_retries: int = 3,
) -> Callable[[str, str, Any], object]:
    """Wrap a ``complete(provider, model, messages)`` entry point for **pre_call** governance
    and the **RETRY** actuator.

    Dispatch is traced via Chronicle ``wrap_llm`` (LIVE envelope + ``on_crossing``).
    TokenOps observes through the crossing hook, not a second ``emit_observation``.

    After each traced dispatch, ``output_runaway`` may set ``controls.retry``; the call is
    re-issued with a tighter output cap and raised frequency/presence penalties, bounded
    by ``max_call_retries`` and by the policy's own retry budget (INJECT once exhausted).
    """
    install_crossing_hook()
    estimate = est_input_fn or estimate_input_tokens
    seg = f"trace:{attr.trace_id}"
    boundary_id = f"{service or attr.agent}.chat"
    traced = wrap_llm(
        boundary_id, dispatch, provider=provider, extract_metadata=policy_metadata(controls)
    )
    controls.compaction_supported = True  # wrap_complete IS the prompt-assembly hook

    def governed(p: str, m: str, messages: Any) -> object:
        owns = wrap_owns_precall(True)
        try:
            controls.begin_call()
            request = CallRequest(
                attr=attr,
                provider=provider,
                model=m,
                estimated_input_tokens=estimate(messages),
                max_output_tokens=controls.call.max_output_tokens,
            )
            governor.pre_call(request)

            use_model = controls.call.model_override or m
            messages = consume_carry(controls, messages)
            if controls.call.compact:  # deep prompt compaction
                messages, compaction = compact_messages(messages, estimate=estimate)
                controls.call.compaction = compaction

            governor.ledger.admit(seg)
            try:
                cap = controls.call.max_output_tokens
                penalties: dict[str, float] = {}
                attempt = 0
                while True:
                    controls.retry = False
                    # Chronicle records + on_crossing → Governor.observe (when bound)
                    response = traced(p, use_model, messages, max_output_tokens=cap, **penalties)
                    if controls.retry and attempt < max_call_retries:
                        attempt += 1
                        cap = tighten_cap(cap)
                        penalties = {"frequency_penalty": 1.0, "presence_penalty": 0.6}
                        continue
                    return response
            finally:
                governor.ledger.complete(seg)
        finally:
            reset_wrap_owns_precall(owns)

    return governed

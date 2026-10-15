"""``wrap_stream``: govern a streaming model call and own the **CANCEL** actuator.

The visible output is consumed as it streams; the moment n-gram degeneration shows up the
stream is cancelled mid-flight (saving the rest of the tokens). The assembled result is traced
through Chronicle ``wrap_llm`` so ``on_crossing`` and ``output_runaway`` can RETRY (re-stream,
tighter) or INJECT. There is no HALT here: the breakers backstop any hard stop.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from chronicle import wrap_llm

from tokenops.capabilities.complete_wrapper import DispatchFn, policy_metadata, tighten_cap
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
from tokenops.framework.policies._util import max_ngram_repeat

__all__ = ["wrap_stream"]


@dataclass
class _StreamResult:
    """Lean llm result assembled from streamed chunks.

    Duck-types ``ModelResponse`` for ``observation_from_crossing``, which reads ``.content``,
    ``.input_tokens`` and ``.output_tokens``.
    """

    content: str
    input_tokens: int
    output_tokens: int


def _stream_and_watch(
    stream_dispatch: DispatchFn,
    provider: str,
    model: str,
    messages: Any,
    *,
    cap: int | None,
    penalties: dict[str, float],
    ngram: int,
    repeats: int,
    check_every: int,
) -> tuple[bool, str]:
    """Consume the stream, watching for n-gram degeneration. On a hit, CANCEL (close the
    generator mid-flight to stop the token bleed) and return early."""
    gen: Any = stream_dispatch(provider, model, messages, max_output_tokens=cap, **penalties)
    acc: list[str] = []
    cancelled = False
    try:
        for i, chunk in enumerate(gen, 1):
            acc.append(str(chunk))
            if i % check_every == 0 and max_ngram_repeat("".join(acc), ngram) >= repeats:
                cancelled = True
                gen.close()  # CANCEL: hard-break the stream
                break
    finally:
        with contextlib.suppress(Exception):  # already closed or finished
            gen.close()
    return cancelled, "".join(acc)


def wrap_stream(
    governor: Governor,
    controls: ApplyControls,
    attr: Attribution,
    *,
    provider: str,
    model: str,
    stream_dispatch: DispatchFn,
    service: str = "",
    ngram: int = 3,
    repeats: int = 4,
    check_every: int = 4,
    max_call_retries: int = 3,
    on_cancel: Callable[[], None] | None = None,
) -> Callable[[str, str, Any], object]:
    """Streaming variant of ``wrap_complete`` that owns the **CANCEL** actuator."""
    install_crossing_hook()
    seg = f"trace:{attr.trace_id}"
    estimate = estimate_input_tokens
    boundary_id = f"{service or attr.agent}.chat"
    cancel_flag = {"cancelled": False}

    def _stream_once(
        p: str,
        use_model: str,
        messages: Any,
        max_output_tokens: int | None = None,
        **penalties: float,
    ) -> _StreamResult:
        cancelled, text = _stream_and_watch(
            stream_dispatch,
            p,
            use_model,
            messages,
            cap=max_output_tokens,
            penalties=penalties,
            ngram=ngram,
            repeats=repeats,
            check_every=check_every,
        )
        cancel_flag["cancelled"] = cancelled
        return _StreamResult(
            content=text,
            input_tokens=estimate(messages),
            output_tokens=max(1, len(text) // 4),
        )

    traced = wrap_llm(
        boundary_id,
        _stream_once,
        provider=provider,
        extract_metadata=policy_metadata(controls),
    )

    def governed(p: str, m: str, messages: Any) -> object:
        owns = wrap_owns_precall(True)
        try:
            controls.begin_call()
            governor.pre_call(
                CallRequest(
                    attr=attr,
                    provider=provider,
                    model=m,
                    estimated_input_tokens=estimate(messages),
                    max_output_tokens=controls.call.max_output_tokens,
                )
            )
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
                    cancel_flag["cancelled"] = False
                    resp = traced(p, use_model, messages, max_output_tokens=cap, **penalties)
                    if cancel_flag["cancelled"] and on_cancel:
                        on_cancel()
                    if (cancel_flag["cancelled"] or controls.retry) and attempt < max_call_retries:
                        attempt += 1
                        cap = tighten_cap(cap)
                        penalties = {"frequency_penalty": 1.0, "presence_penalty": 0.6}
                        continue
                    return resp
            finally:
                governor.ledger.complete(seg)
        finally:
            reset_wrap_owns_precall(owns)

    return governed

"""Integration — the brownfield IN tap that drops into a vanilla agent.

``make_on_step`` returns a callback you pass straight into an existing agent's
``on_step=...`` hook. It maps the agent's own step object to an ``Observation`` and feeds
the Governor. If a policy HALTs, ``Halt`` propagates out of the agent's loop — which is
exactly the brownfield control channel, with no change to agent logic.

The adapter **duck-types** the step object (reads ``.action`` / ``.query`` / ``.tokens``),
so ``tokenops.control`` never imports agent code — the dependency stays one-way.

LLM path: ``wrap_complete`` / ``wrap_stream`` keep pre_call (MUTATE / HALT / RETRY) in
TokenOps, but dispatch goes through Chronicle ``wrap_llm`` so LIVE record +
``on_crossing`` fire. The TokenOps crossing hook projects crossings →
``Governor.observe`` — do not also ``emit_observation`` here (double-billing).
"""

from __future__ import annotations

import hashlib
import itertools
import json
from collections.abc import Callable, Sequence

from chronicle import wrap_llm

from tokenops.control.context import current_span
from tokenops.control.core import Attribution, CallRequest, Observation, Usage
from tokenops.control.crossing import install_crossing_hook


def tool_signature(name: str, args) -> str:
    payload = json.dumps([name, args], sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _hash(text: object) -> str:
    return hashlib.sha256(str(text).encode()).hexdigest()[:16]


def _span_fields(*, service: str = "") -> dict:
    span = current_span()
    if span is None:
        return {"service": service, "span_id": "", "parent_span_id": None}
    return {
        "service": span.service or service,
        "span_id": span.span_id,
        "parent_span_id": span.parent_span_id,
    }


def step_to_observation(
    step,
    attr: Attribution,
    *,
    ts: float,
    provider: str = "",
    model: str = "",
    service: str = "",
) -> Observation:
    """Map an agent step object to an ``Observation`` with ``boundary_tags``."""
    action = getattr(step, "action", "")
    span = _span_fields(service=service)
    if action == "model":
        tu = getattr(step, "tokens", None)
        usage = Usage(
            input=getattr(tu, "input_tokens", 0) if tu else 0,
            output=getattr(tu, "output_tokens", 0) if tu else 0,
        )
        boundary_tags = {
            "node_type": "llm",
            "provider": provider,
            "model": model,
        }
        return Observation(
            attr=attr,
            node_type="llm",
            boundary_id=f"{getattr(step, 'agent', span['service'] or 'agent')}.chat",
            ts=ts,
            usage=usage,
            provider=provider,
            model=model,
            output={"text": getattr(step, "detail", "")},
            boundary_tags=boundary_tags,
            **span,
        )
    if action == "delegate":
        boundary_tags = {"node_type": "delegate", "target": getattr(step, "detail", "")}
        return Observation(
            attr=attr,
            node_type="delegate",
            boundary_id="delegate",
            ts=ts,
            input={"target_agent": getattr(step, "detail", "")},
            boundary_tags=boundary_tags,
            **span,
        )
    query = getattr(step, "query", "")
    args = {"query": query}
    tool_name = action or "tool"
    boundary_tags = {"node_type": "tool", "tool": tool_name}
    return Observation(
        attr=attr,
        node_type="tool",
        boundary_id=tool_name,
        ts=ts,
        input={"name": tool_name, "args": args},
        output={
            "completeness": getattr(step, "completeness", None),
            "snippet": getattr(step, "detail", ""),
        },
        signature=tool_signature(tool_name, args),
        result_hash=_hash(getattr(step, "detail", "")),
        boundary_tags=boundary_tags,
        **span,
    )


def make_on_step(governor, attr: Attribution, *, provider: str, model: str, service: str = ""):
    """Return a callback for an agent's ``on_step``."""
    counter = itertools.count(1)

    def on_step(ev) -> None:
        obs = step_to_observation(
            ev,
            attr,
            ts=float(next(counter)),
            provider=provider,
            model=model,
            service=service,
        )
        governor.observe(obs)

    return on_step


#: A dispatch callable: (provider, model, messages, max_output_tokens) -> response.
DispatchFn = Callable[..., object]


def _estimate_input_tokens(messages) -> int:
    return max(1, len(str(messages)) // 4)


_RETRY_BASE_CAP = 512


def _tighten_cap(cap: int | None) -> int:
    """RETRY tightens the output cap each attempt (halve, floor 64)."""
    return max(64, (cap or _RETRY_BASE_CAP) // 2)


def apply_carry_to_messages(
    messages,
    carry: Sequence[str],
    *,
    as_user: Callable[[str], object] | None = None,
) -> list:
    """Append governance INJECT directives as the final user turns.

    Steer messages belong at the end of the context so recency favors the correction
    over stale task history — not as a prepended system slot."""
    if not carry:
        return list(messages)
    out = list(messages)
    for text in carry:
        if as_user is not None:
            out.append(as_user(text))
        else:
            out.append({"role": "user", "content": text})
    return out


def consume_carry(
    controls,
    messages,
    *,
    as_user: Callable[[str], object] | None = None,
) -> list:
    """Apply pending ``controls.carry`` injects and clear the queue."""
    out = apply_carry_to_messages(messages, controls.carry, as_user=as_user)
    controls.carry.clear()
    return out


def _compact_messages(messages):
    """Deep context_compaction MUTATE: rewrite the outgoing messages — pin every system
    message, drop duplicate non-system messages (deduped tool outputs / repeated context)."""
    seen: set = set()
    out: list = []
    for msg in messages:
        role = msg.get("role") if isinstance(msg, dict) else None
        content = msg.get("content", "") if isinstance(msg, dict) else str(msg)
        if role == "system":
            out.append(msg)
            continue
        if isinstance(content, str) and content.startswith("[TokenOps trajectory hint"):
            out.append(msg)
            continue
        key = (role, content)
        if key in seen:
            continue
        seen.add(key)
        out.append(msg)
    return out


def wrap_complete(
    governor,
    controls,
    attr: Attribution,
    *,
    provider: str,
    model: str,
    dispatch: DispatchFn,
    est_input_fn: Callable[[object], int] | None = None,
    service: str = "",
    max_call_retries: int = 3,
):
    """Wrap a ``complete(provider, model, messages)`` entry point for **pre_call** governance
    and the **RETRY** actuator.

    Dispatch is traced via Chronicle ``wrap_llm`` (LIVE envelope + ``on_crossing``).
    TokenOps observes through the crossing hook — not a second ``emit_observation``.

    After each traced dispatch, ``output_runaway`` may set ``controls.retry``; the call is
    re-issued with a tighter output cap and raised frequency/presence penalties — bounded
    by ``max_call_retries`` and by the policy's own retry budget (INJECT once exhausted).
    """
    install_crossing_hook()
    estimate = est_input_fn or _estimate_input_tokens
    seg = f"run:{attr.run_id}"
    boundary_id = f"{service or attr.agent}.chat"
    traced = wrap_llm(boundary_id, dispatch)

    def governed(p: str, m: str, messages) -> object:
        from tokenops.control.crossing import reset_wrap_owns_precall, wrap_owns_precall

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
                messages = _compact_messages(messages)

            governor.ledger.admit(seg)
            try:
                cap = controls.call.max_output_tokens
                penalties: dict = {}
                attempt = 0
                while True:
                    controls.retry = False
                    # Chronicle records + on_crossing → Governor.observe (when bound)
                    response = traced(p, use_model, messages, max_output_tokens=cap, **penalties)
                    if controls.retry and attempt < max_call_retries:
                        attempt += 1
                        cap = _tighten_cap(cap)
                        penalties = {"frequency_penalty": 1.0, "presence_penalty": 0.6}
                        continue
                    return response
            finally:
                governor.ledger.complete(seg)
        finally:
            reset_wrap_owns_precall(owns)

    return governed


from dataclasses import dataclass as _dataclass


@_dataclass
class _StreamResult:
    """Lean llm result assembled from streamed chunks (duck-types ModelResponse for
    ``observation_from_crossing``: it reads ``.content`` / ``.input_tokens`` / ``.output_tokens``)."""

    content: str
    input_tokens: int
    output_tokens: int


def _stream_and_watch(
    stream_dispatch,
    p,
    model,
    messages,
    *,
    cap,
    penalties,
    ngram: int,
    repeats: int,
    check_every: int,
) -> tuple[bool, str]:
    """Consume the stream, watching for n-gram degeneration. On a hit, CANCEL — close the
    generator mid-flight to stop the token bleed — and return early."""
    from tokenops.control.policies._util import max_ngram_repeat

    gen = stream_dispatch(p, model, messages, max_output_tokens=cap, **penalties)
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
        try:
            gen.close()
        except Exception:
            pass
    return cancelled, "".join(acc)


def wrap_stream(
    governor,
    controls,
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
):
    """Streaming variant of ``wrap_complete`` that owns the **CANCEL** actuator.

    Streams the visible output, and the moment it detects degeneration it **cancels the
    stream mid-flight** (saving the rest of the tokens). The assembled result is traced
    via Chronicle ``wrap_llm`` so ``on_crossing`` → ``output_runaway`` can RETRY
    (re-stream, tighter) or INJECT. No HALT — the breakers backstop any hard stop.
    """
    install_crossing_hook()
    seg = f"run:{attr.run_id}"
    estimate = _estimate_input_tokens
    boundary_id = f"{service or attr.agent}.chat"
    cancel_flag = {"cancelled": False}

    def _stream_once(p, use_model, messages, max_output_tokens=None, **penalties):
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

    traced = wrap_llm(boundary_id, _stream_once)

    def governed(p: str, m: str, messages) -> object:
        from tokenops.control.crossing import reset_wrap_owns_precall, wrap_owns_precall

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
                messages = _compact_messages(messages)

            governor.ledger.admit(seg)
            try:
                cap = controls.call.max_output_tokens
                penalties: dict = {}
                attempt = 0
                while True:
                    controls.retry = False
                    cancel_flag["cancelled"] = False
                    resp = traced(p, use_model, messages, max_output_tokens=cap, **penalties)
                    if cancel_flag["cancelled"] and on_cancel:
                        on_cancel()
                    if (cancel_flag["cancelled"] or controls.retry) and attempt < max_call_retries:
                        attempt += 1
                        cap = _tighten_cap(cap)
                        penalties = {"frequency_penalty": 1.0, "presence_penalty": 0.6}
                        continue
                    return resp
            finally:
                governor.ledger.complete(seg)
        finally:
            reset_wrap_owns_precall(owns)

    return governed

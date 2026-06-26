"""Integration — the brownfield IN tap that drops into a vanilla agent.

``make_on_step`` returns a callback you pass straight into an existing agent's
``on_step=...`` hook. It maps the agent's own step object to a contract ``Observation`` and
feeds the Governor. If a policy HALTs, ``Halt`` propagates out of the agent's loop — which
is exactly the brownfield control channel, with no change to agent logic.

The adapter **duck-types** the step object (reads ``.action`` / ``.query`` / ``.tokens``),
so ``tokenops.control`` never imports ``tokenops.agents`` — the dependency stays one-way.
"""

from __future__ import annotations

import hashlib
import itertools
import json
from typing import Callable

from tokenops.control.core import Attribution, CallRequest, Observation, Usage


def tool_signature(name: str, args) -> str:
    payload = json.dumps([name, args], sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _hash(text: object) -> str:
    return hashlib.sha256(str(text).encode()).hexdigest()[:16]


def make_on_step(governor, attr: Attribution, *, provider: str, model: str):
    """Return a callback for an agent's ``on_step``.

    Maps each step to an Observation by ``action``:
      * ``model``    → llm crossing (priced from the step's token usage)
      * ``search``/other tool → tool crossing (signature + result_hash for loop detection)
      * ``delegate`` → delegate crossing
    """
    counter = itertools.count(1)

    def on_step(ev) -> None:  # signature matches the agent's existing callback
        i = next(counter)
        action = getattr(ev, "action", "")
        if action == "model":
            tu = getattr(ev, "tokens", None)
            usage = Usage(
                input=getattr(tu, "input_tokens", 0) if tu else 0,
                output=getattr(tu, "output_tokens", 0) if tu else 0,
            )
            obs = Observation(
                attr=attr, node_type="llm", boundary_id=f"{getattr(ev, 'agent', 'agent')}.chat",
                ts=float(i), provider=provider, model=model, usage=usage,
                output={"text": getattr(ev, "detail", "")},
            )
        elif action == "delegate":
            obs = Observation(
                attr=attr, node_type="delegate", boundary_id="delegate", ts=float(i),
                input={"target_agent": getattr(ev, "detail", "")},
            )
        else:  # tool (search, etc.)
            query = getattr(ev, "query", "")
            args = {"query": query}
            obs = Observation(
                attr=attr, node_type="tool", boundary_id=action or "tool", ts=float(i),
                input={"name": action or "tool", "args": args},
                output={"completeness": getattr(ev, "completeness", None),
                        "snippet": getattr(ev, "detail", "")},
                signature=tool_signature(action or "tool", args),
                result_hash=_hash(getattr(ev, "detail", "")),
            )
        governor.observe(obs)  # may raise Halt, which unwinds the agent loop

    return on_step


#: A dispatch callable: (provider, model, messages, max_output_tokens) -> response.
DispatchFn = Callable[..., object]


def _estimate_input_tokens(messages) -> int:
    return max(1, len(str(messages)) // 4)  # chars/4; never tokenize on the hot path


def wrap_complete(
    governor,
    controls,
    attr: Attribution,
    *,
    provider: str,
    model: str,
    dispatch: DispatchFn,
    est_input_fn: Callable[[object], int] | None = None,
):
    """Wrap a ``complete(provider, model, messages)`` entry point so the **pre_call** moment
    runs and corrective controls actually apply.

    The returned callable matches the agent's ``complete`` signature, so you swap it in with
    ``monkeypatch.setattr(agent_module, "complete", governed)`` (or pass it directly). Per
    call it:

      1. resets per-call mutation state, estimates input tokens, builds a ``CallRequest``;
      2. runs ``governor.pre_call`` — HALT raises, REJECT/QUEUE raise ``Throttled``, MUTATE
         records a model/output-cap override, INJECT/compaction records a carry message;
      3. admits the call to ``inflight`` (concurrency), dispatches the **mutated** call
         (swapped model, enforced ``max_output_tokens``, carry messages prepended), and
         completes ``inflight`` in a ``finally``.

    Requires an :class:`ApplyControls`-style ``controls`` (the one registered on ``governor``)
    so the wrap can read what pre_call decided.
    """
    counter = itertools.count(1)
    estimate = est_input_fn or _estimate_input_tokens
    seg = f"run:{attr.run_id}"

    def governed(p: str, m: str, messages) -> object:
        controls.begin_call()
        request = CallRequest(
            attr=attr, provider=provider, model=m,
            estimated_input_tokens=estimate(messages),
            max_output_tokens=controls.call.max_output_tokens,
        )
        governor.pre_call(request)  # applies MUTATE into controls.call; may raise Halt/Throttled

        use_model = controls.call.model_override or m
        if controls.carry:
            messages = [{"role": "system", "content": c} for c in controls.carry] + list(messages)
            controls.carry.clear()

        governor.ledger.admit(seg)
        try:
            return dispatch(p, use_model, messages, max_output_tokens=controls.call.max_output_tokens)
        finally:
            governor.ledger.complete(seg)

    return governed

"""Cache affinity: one routing hint per run, fail-soft once, no change to the request."""

from __future__ import annotations

import pytest

from conftest import toy_price
from tokenops.capabilities import wrap_complete, wrap_stream
from tokenops.framework.attribution import _build_attribution
from tokenops.framework.context import SpanContext, _governance_scope, run_scope
from tokenops.framework.engine import ApplyControls, Governor
from tokenops.framework.ledger import Ledger
from tokenops.framework.models import HopAttribution
from tokenops.providers.cache_affinity import (
    BodyField,
    Header,
    NoAffinity,
    affinity_for,
    open_affinity_run,
    run_key,
)
from tokenops.providers.types import ModelResponse

MESSAGES = [{"role": "user", "content": "hi"}]


class _KeyRejected(Exception):
    pass


def _setup(trace_id: str, **wrap_kwargs):
    controls = ApplyControls()
    gov = Governor(Ledger(price=toy_price), controls)
    reg = HopAttribution(trace_id=trace_id, intent="t", user_dims={"user_id": "alice"})
    attr = _build_attribution(reg, service="svc")
    gov.ledger.open_run(trace_id)
    return gov, controls, reg, attr


def _call(governed, gov, reg, attr, n: int = 1):
    out = []
    with run_scope(reg, SpanContext(span_id="s1", service="svc")):
        with _governance_scope(gov, attr, provider="openai", model="m"):
            for _ in range(n):
                out.append(governed("openai", "m", MESSAGES))
    return out


def _complete(trace_id: str, dispatch, **kw):
    gov, controls, reg, attr = _setup(trace_id)
    governed = wrap_complete(
        gov, controls, attr, provider=kw.pop("provider", "openai"), model="m",
        dispatch=dispatch, service="svc", **kw,
    )  # fmt: skip
    return governed, gov, reg, attr


def _recording(fail=None):
    calls: list[dict] = []

    def dispatch(provider, model, messages, max_output_tokens=None, **kw):
        calls.append({"model": model, "messages": messages, "cap": max_output_tokens, **kw})
        if fail and "extra_body" in kw and fail(kw):
            raise _KeyRejected("Unknown parameter: 'prompt_cache_key'")
        return ModelResponse(content="ok", input_tokens=10, output_tokens=5)

    return dispatch, calls


def test_body_field_returns_a_copy_and_keeps_other_entries() -> None:
    kwargs = {"extra_body": {"other": 1}, "max_output_tokens": 5}
    out = BodyField().apply(kwargs, "k")
    assert out == {"extra_body": {"other": 1, "prompt_cache_key": "k"}, "max_output_tokens": 5}
    assert kwargs == {"extra_body": {"other": 1}, "max_output_tokens": 5}


def test_header_and_none_strategies() -> None:
    kwargs = {"extra_headers": {"a": "b"}}
    assert Header("x-session-affinity").apply(kwargs, "k") == {
        "extra_headers": {"a": "b", "x-session-affinity": "k"}
    }
    assert kwargs == {"extra_headers": {"a": "b"}}
    same = {"x": 1}
    assert NoAffinity().apply(same, "k") is same


def test_registry_and_modes() -> None:
    assert isinstance(affinity_for("azure/gpt-5-mini"), BodyField)
    assert isinstance(affinity_for("OpenAI"), BodyField)
    assert isinstance(affinity_for("somewhere-else"), NoAffinity)
    assert open_affinity_run(None, "openai", "t").status == "off"
    assert open_affinity_run("off", "openai", "t").status == "off"
    assert open_affinity_run("auto", "somewhere-else", "t").status == "off"
    assert open_affinity_run({"mode": {"header": "x-h"}}, "x", "t").strategy == Header("x-h")
    assert open_affinity_run({"mode": "auto", "key": "fixed:dbg"}, "openai", "t").key == "dbg"
    for bad in ("sometimes", {"mode": "auto", "nope": 1}, {"mode": "auto", "key": "tenant"}):
        with pytest.raises(ValueError):
            open_affinity_run(bad, "openai", "t")


def test_two_runs_get_different_keys() -> None:
    assert run_key("a" * 32) != run_key("b" * 32)
    assert run_key("a" * 32) == run_key("a" * 32)


def test_one_run_sends_the_same_key_on_every_call(chronicle_envelopes) -> None:
    dispatch, calls = _recording()
    governed, gov, reg, attr = _complete("a" * 32, dispatch, cache_affinity="auto")
    _call(governed, gov, reg, attr, n=3)
    keys = {c["extra_body"]["prompt_cache_key"] for c in calls}
    assert keys == {run_key("a" * 32)}
    assert {e.metadata["tokenops.cache_affinity"] for e in chronicle_envelopes} == {"sent"}


def test_mode_off_sends_nothing(chronicle_envelopes) -> None:
    dispatch, calls = _recording()
    governed, gov, reg, attr = _complete("b" * 32, dispatch)
    _call(governed, gov, reg, attr)
    assert "extra_body" not in calls[0] and "extra_headers" not in calls[0]
    assert not any(k.startswith("tokenops.cache") for k in chronicle_envelopes[0].metadata)


def test_a_refused_hint_is_resent_once_and_the_run_stays_unkeyed(chronicle_envelopes) -> None:
    dispatch, calls = _recording(fail=lambda kw: True)
    governed, gov, reg, attr = _complete("c" * 32, dispatch, cache_affinity="auto")
    _call(governed, gov, reg, attr, n=2)
    assert ["extra_body" in c for c in calls] == [True, False, False]
    assert chronicle_envelopes[-1].metadata["tokenops.cache_affinity"] == "refused"


def test_an_unrelated_error_is_raised_and_keeps_the_hint() -> None:
    state = {"n": 0}

    def dispatch(provider, model, messages, max_output_tokens=None, **kw):
        state["n"] += 1
        if state["n"] == 1:
            raise RuntimeError("content filter triggered")
        return ModelResponse(content="ok", input_tokens=1, output_tokens=1)

    governed, gov, reg, attr = _complete("d" * 32, dispatch, cache_affinity="auto")
    with pytest.raises(RuntimeError, match="content filter"):
        _call(governed, gov, reg, attr)
    with run_scope(reg, SpanContext(span_id="s2", service="svc")):
        with _governance_scope(gov, attr, provider="openai", model="m"):
            governed("openai", "m", MESSAGES)
    assert state["n"] == 2


def test_the_request_is_identical_with_and_without_affinity() -> None:
    off, off_calls = _recording()
    on, on_calls = _recording()
    for dispatch, kw in ((off, {}), (on, {"cache_affinity": "auto"})):
        governed, gov, reg, attr = _complete("e" * 32, dispatch, **kw)
        _call(governed, gov, reg, attr)
    strip = lambda c: {k: v for k, v in c.items() if k != "extra_body"}  # noqa: E731
    assert strip(on_calls[0]) == strip(off_calls[0])


def test_stream_wrapper_applies_and_falls_back() -> None:
    seen: list[dict] = []

    def stream_dispatch(provider, model, messages, max_output_tokens=None, **kw):
        seen.append(dict(kw))
        if "extra_body" in kw:
            raise _KeyRejected("Unknown parameter: 'prompt_cache_key'")
        yield "ok"

    gov, controls, reg, attr = _setup("f" * 32)
    governed = wrap_stream(
        gov, controls, attr, provider="openai", model="m",
        stream_dispatch=stream_dispatch, service="svc", cache_affinity="auto",
    )  # fmt: skip
    _call(governed, gov, reg, attr, n=2)
    assert ["extra_body" in c for c in seen] == [True, False, False]

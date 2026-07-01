"""model_router — proactive routing by complexity (easy→cheap, hard→strong)."""

from __future__ import annotations

from tokenops.control import ActionKind, CallRequest
from tokenops.control.policies import model_router
from tokenops.control.policies._util import classify_complexity
from conftest import make_attr, FakeView


def _req(route_hint, model):
    return CallRequest(attr=make_attr(), provider="openai", model=model, route_hint=route_hint)


def test_classify_complexity():
    assert classify_complexity([{"role": "user", "content": "click the submit button"}]) == "easy"
    assert classify_complexity([{"role": "user", "content": "summarize and analyze this report"}]) == "hard"


def test_easy_routes_to_cheap():
    det, pol = model_router.build(easy_model="gpt-4o-mini", hard_model="gpt-4o")
    sig = det.pre_call(_req("easy", "gpt-4o"), FakeView())  # currently on the strong model
    a = pol.decide(sig, FakeView())
    assert a.kind is ActionKind.MUTATE and a.downgrade_to == "gpt-4o-mini"


def test_hard_routes_to_strong():
    det, pol = model_router.build(easy_model="gpt-4o-mini", hard_model="gpt-4o")
    sig = det.pre_call(_req("hard", "gpt-4o-mini"), FakeView())
    assert pol.decide(sig, FakeView()).downgrade_to == "gpt-4o"


def test_no_signal_when_already_right_tier():
    det, _ = model_router.build(easy_model="gpt-4o-mini", hard_model="gpt-4o")
    assert det.pre_call(_req("easy", "gpt-4o-mini"), FakeView()) is None

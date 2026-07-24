"""Run registration and attribution."""

from __future__ import annotations

import pytest

from tokenops.control.attribution import (
    _build_attribution,
    begin_downstream_run,
    begin_entry_run,
    require_registration,
)
from tokenops.control.context import RUN_ID_HEADER, clear, current_registration, current_span
from tokenops.control.integration import step_to_observation
from tokenops.control.models import (
    RunAlreadyRegisteredError,
    RunNotRegisteredError,
    RunRegistration,
)
from tokenops.control.store import Store


@pytest.fixture
def store(tmp_path):
    s = Store(str(tmp_path / "attr.db"))
    yield s
    s.close()


def test_register_and_resolve(store):
    reg = store.register_run(
        RunRegistration(run_id="r1", intent="frontier", user_dims={"Country": "US"})
    )
    assert reg.intent == "frontier"
    resolved = store.resolve_run("r1")
    assert resolved.user_dims["Country"] == "US"


def test_duplicate_register_fails(store):
    store.register_run(RunRegistration(run_id="r1"))
    with pytest.raises(RunAlreadyRegisteredError):
        store.register_run(RunRegistration(run_id="r1", intent="other"))


def test_resolve_missing_fails_closed(store):
    with pytest.raises(RunNotRegisteredError):
        store.resolve_run("missing")


def test_begin_entry_run_binds_context(store):
    clear()
    bound = begin_entry_run(
        store,
        headers={},
        payload={"intent": "demo", "user_dims": {"IsFortune500": "true"}},
        service="research",
        run_id="run-a",
    )
    assert bound.registration.run_id == "run-a"
    assert current_registration().intent == "demo"
    assert current_span().service == "research"
    clear()


def test_begin_downstream_soft_registers_when_header_missing(store, caplog):
    clear()
    import logging

    with caplog.at_level(logging.WARNING, logger="tokenops.attribution"):
        bound = begin_downstream_run(store, headers={}, service="summarize")
    assert bound.registration.intent == "unattributed"
    assert bound.registration.user_dims.get("tokenops_soft_run") == "1"
    assert bound.span.service == "summarize"
    assert any("missing_run_id" in r.message for r in caplog.records)
    clear()


def test_begin_downstream_resolves_registration(store):
    store.register_run(RunRegistration(run_id="run-a", intent="x", user_dims={"k": "v"}))
    clear()
    bound = begin_downstream_run(
        store,
        headers={RUN_ID_HEADER: "run-a", "X-TokenOps-Parent-Span-Id": "span-parent"},
        service="summarize",
    )
    assert bound.registration.intent == "x"
    assert bound.span.parent_span_id == "span-parent"
    assert bound.span.service == "summarize"
    clear()


def test_build_attribution_maps_service_and_user_dims(store):
    reg = RunRegistration(
        run_id="r1", intent="f500", user_dims={"user_id": "alice", "Country": "US"}
    )
    attr = _build_attribution(reg, service="research")
    assert attr.run_id == "r1"
    assert attr.agent == "research"
    assert attr.user == "alice"
    assert attr.tags["intent"] == "f500"
    assert attr.tags["Country"] == "US"


def test_require_registration_fail_closed():
    clear()
    with pytest.raises(RunNotRegisteredError):
        require_registration()


def test_step_to_observation_boundary_tags():
    from types import SimpleNamespace

    from conftest import make_attr

    step = SimpleNamespace(
        action="model",
        agent="research",
        detail="d",
        tokens=SimpleNamespace(input_tokens=1, output_tokens=2),
    )
    obs = step_to_observation(
        step, make_attr(), ts=1.0, provider="openai", model="gpt-4o-mini", service="research"
    )
    assert obs.boundary_tags["node_type"] == "llm"
    assert obs.boundary_tags["provider"] == "openai"
    assert obs.boundary_tags["model"] == "gpt-4o-mini"
    assert obs.service == "research"

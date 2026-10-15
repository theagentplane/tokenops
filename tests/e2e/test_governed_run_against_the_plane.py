"""End to end: a governed agent against a real control plane and a scripted model.

Real: the control plane (HTTP, SQLite), Chronicle recording and replay, the TokenOps governor,
ledger, hook and background writer. Scripted: the model.
"""

from __future__ import annotations

import time
from importlib.metadata import PackageNotFoundError, version

import chronicle
import pytest
from chronicle import ReplayPlan

from tokenops import flush_ledger_writes, tokenops_run
from tokenops.capabilities import wrap_complete
from tokenops.framework.core import Halt
from tokenops.providers.types import ModelResponse
from tokenops.repositories import ControlPlaneClient, PrecheckRequest

try:
    _PLANE_MAJOR = int(version("agentplane-control-plane").split(".")[0])
except PackageNotFoundError:  # pragma: no cover - environment dependent
    _PLANE_MAJOR = 0

pytestmark = pytest.mark.skipif(
    _PLANE_MAJOR < 1, reason="needs agentplane-control-plane>=1.0 installed"
)

# 100_000 input tokens on gpt-4o-mini is 15_000 micros; the cap below allows three calls.
CALL_TOKENS = 100_000
CAP_MICROS = 50_000


def _scripted_model(provider, model, messages, max_output_tokens=None, **kwargs):
    return ModelResponse(content="answer", input_tokens=CALL_TOKENS, output_tokens=0)


@chronicle.boundary("search", kind="tool")
def search(query: str) -> dict:
    return {"snippet": f"result for {query}"}


def _agent(governed, calls: int) -> int:
    """The agent under test: search, then ask the model, ``calls`` times."""
    done = 0
    for i in range(calls):
        found = search(f"q{i}")
        governed("openai", "gpt-4o-mini", [{"role": "user", "content": found["snippet"]}])
        done += 1
    return done


def _governed(bound, service: str):
    return wrap_complete(
        bound.governor,
        bound.controls,
        bound.attr,
        provider="openai",
        model="gpt-4o-mini",
        dispatch=_scripted_model,
        service=service,
    )


@pytest.fixture
def plane():
    from local_plane import LocalPlane

    with LocalPlane() as p:
        yield p


def _client(plane) -> ControlPlaneClient:
    from local_plane import API_KEY

    return ControlPlaneClient(plane.url, api_key=API_KEY)


def test_a_governed_agent_trips_its_budget_and_the_halt_is_on_the_trace(plane):
    plane.configure_cost_cap(CAP_MICROS)
    client = _client(plane)

    with chronicle.record("budget-incident") as session:
        trace_id = session.trace_id
        with tokenops_run(client=client, service="agent") as bound:
            governed = _governed(bound, "agent")
            with pytest.raises(Halt) as halted:
                _agent(governed, calls=10)
    assert "run_llm_cap" in halted.value.action.reason

    assert flush_ledger_writes(10)
    status = client.halt_status(trace_id)
    assert status.halted is True
    assert "run_llm_cap" in (status.reason or "")

    trace = plane.wait_for_trace(trace_id)
    attributes = trace["attributes"]
    assert attributes["tokenops.halted"] is True
    assert "run_llm_cap" in attributes["tokenops.halt_reason"]
    assert any(t["trace_id"] == trace_id for t in client.traces(halted_only=True))


def test_two_agents_share_one_budget_and_the_second_is_stopped_by_the_first(plane):
    plane.configure_cost_cap(CAP_MICROS)
    client_a, client_b = _client(plane), _client(plane)

    with chronicle.record("two-agents") as session:
        trace_id = session.trace_id
        with tokenops_run(client=client_a, service="researcher") as a:
            assert _agent(_governed(a, "researcher"), calls=2) == 2  # 30_000 of 50_000
        assert flush_ledger_writes(10)

        with tokenops_run(client=client_b, service="writer") as b:
            governed_b = _governed(b, "writer")
            with pytest.raises(Halt):
                _agent(governed_b, calls=10)  # only one call fits in what is left
            assert b.governor.ledger.cost_micros(trace_id) > CAP_MICROS

    assert flush_ledger_writes(10)
    # The shared accumulator holds both agents' spend and is over the cap.
    state = client_a.precheck(
        PrecheckRequest(
            trace_id=trace_id,
            segment_keys=[f"trace:{trace_id}"],
            budgets=[
                {
                    "budget_id": "__trace_total__",
                    "segment_key": f"trace:{trace_id}",
                    "period": "lifetime",
                }
            ],
        )
    )
    assert state.halted is True
    assert sum(state.spent.values()) > CAP_MICROS


def test_replaying_a_halted_trace_with_the_fix_is_allowed(plane):
    """Record the incident, replay it to reproduce the halt, raise the cap, replay: allowed."""
    plane.configure_cost_cap(CAP_MICROS)
    client = _client(plane)

    # 1. The incident: the agent halts after three of six calls.
    with chronicle.record("incident") as session:
        trace_id, span_id = session.trace_id, session.span_id
        with tokenops_run(client=client, service="agent") as bound:
            with pytest.raises(Halt):
                _agent(_governed(bound, "agent"), calls=6)
    assert flush_ledger_writes(10)
    plane.wait_for_trace(trace_id)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        chronicle.flush()
        spans = plane.trace(trace_id).get("spans", [])
        if any(s.get("state") == "closed" for s in spans):
            break
        time.sleep(0.05)

    # The replay is bounded by what was recorded: the agent reached its fourth search.
    plan = ReplayPlan().stub("search").run("agent.chat")
    capped = {
        "governance": {
            "budgets": [{"id": "run_llm_cap", "limit_micros": CAP_MICROS, "dimension": "trace"}],
            "policies": {"cost_budget": {"budget": "run_llm_cap"}},
        }
    }
    # The fix: a cap large enough for the whole recorded run.
    fixed = {
        "governance": {
            "budgets": [{"id": "run_llm_cap", "limit_micros": 1_000_000, "dimension": "trace"}],
            "policies": {"cost_budget": {"budget": "run_llm_cap"}},
        }
    }

    # 2. Replaying with the original cap reproduces the halt (tools come from the recording).
    with chronicle.replay_trace(trace_id, span_id, plan):
        with tokenops_run(config=capped, service="agent") as bound:
            with pytest.raises(Halt):
                _agent(_governed(bound, "agent"), calls=4)

    # 3. Replaying with the fix lets the call that was halted go through.
    with chronicle.replay_trace(trace_id, span_id, plan) as run:
        with tokenops_run(config=fixed, service="agent") as bound:
            completed = _agent(_governed(bound, "agent"), calls=4)

    assert completed == 4
    assert run.invocation_count("agent.chat") == 4

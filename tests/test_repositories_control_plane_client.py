"""Unit tests for the control-plane 1.0 client (no network: ``httpx.MockTransport``)."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from tokenops.repositories import (
    ControlPlaneClient,
    ControlPlaneError,
    ControlPlaneUnavailable,
    LedgerEvent,
    PrecheckRequest,
)

GOV = {"governance": {"budgets": [], "policies": {"step_cap": {"max_steps": 3}}}}


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> ControlPlaneClient:
    return ControlPlaneClient("http://plane", api_key="k", transport=httpx.MockTransport(handler))


def test_governance_sends_bearer_and_caches_etag():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.headers.get("If-None-Match") == '"v1"':
            return httpx.Response(304)
        return httpx.Response(200, json=GOV, headers={"ETag": '"v1"'})

    client = _client(handler)
    first = client.governance("research")
    second = client.governance("research")

    assert first.config == GOV and first.etag == '"v1"' and not first.stale
    assert second.config == GOV and not second.stale
    assert seen[0].headers["Authorization"] == "Bearer k"
    assert "If-None-Match" not in seen[0].headers
    assert seen[1].headers["If-None-Match"] == '"v1"'


def test_governance_returns_independent_copies():
    client = _client(lambda r: httpx.Response(200, json=GOV, headers={"ETag": '"v1"'}))
    first = client.governance("a")
    first.config["governance"]["policies"].clear()
    assert client.governance("a").config == GOV


def test_governance_is_stale_when_unreachable_after_a_success():
    state = {"up": True}

    def handler(request: httpx.Request) -> httpx.Response:
        if not state["up"]:
            raise httpx.ConnectError("down", request=request)
        return httpx.Response(200, json=GOV, headers={"ETag": '"v1"'})

    client = _client(handler)
    client.governance("research")
    state["up"] = False
    result = client.governance("research")
    assert result.stale is True
    assert result.config == GOV


def test_governance_is_stale_on_5xx_after_a_success():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(200, json=GOV, headers={"ETag": '"v1"'})
        return httpx.Response(503)

    client = _client(handler)
    client.governance("research")
    assert client.governance("research").stale is True


def test_governance_unreachable_without_cache_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    with pytest.raises(ControlPlaneUnavailable):
        _client(handler).governance("research")


def test_governance_4xx_is_never_masked_by_the_cache():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(200, json=GOV, headers={"ETag": '"v1"'})
        return httpx.Response(403, json={"detail": "forbidden"})

    client = _client(handler)
    client.governance("research")
    with pytest.raises(ControlPlaneError) as caught:
        client.governance("research")
    assert caught.value.status_code == 403
    assert not isinstance(caught.value, ControlPlaneUnavailable)


def test_clear_governance_cache_forces_a_refetch():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=GOV, headers={"ETag": '"v1"'})

    client = _client(handler)
    client.governance("a")
    client.clear_governance_cache("a")
    client.governance("a")
    assert all("If-None-Match" not in r.headers for r in seen)


def test_precheck_round_trip():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert request.url.path == "/v1/ledger/precheck"
        assert body["trace_id"] == "a" * 32
        assert body["segment_keys"] == ["trace:" + "a" * 32]
        return httpx.Response(
            200,
            json={
                "server_ts": 12.5,
                "halted": True,
                "halt_reason": "budget",
                "spent": {"run_llm_cap|trace:x|lifetime": 40},
                "inflight": {"trace:x": 2},
            },
        )

    result = _client(handler).precheck(
        PrecheckRequest(trace_id="a" * 32, segment_keys=["trace:" + "a" * 32])
    )
    assert result.halted is True and result.halt_reason == "budget"
    assert result.spent == {"run_llm_cap|trace:x|lifetime": 40}
    assert result.inflight == {"trace:x": 2}
    assert result.server_ts == 12.5


def test_apply_events_sends_the_batch_in_order_and_parses_the_result():
    events: list[LedgerEvent] = [
        {"kind": "admit", "trace_id": "t", "segment_key": "trace:t"},
        {
            "kind": "spent_add",
            "trace_id": "t",
            "delta_micros": 5,
            "targets": [{"budget_id": "b", "segment_key": "trace:t", "period": "lifetime"}],
        },
        {"kind": "complete", "trace_id": "t", "segment_key": "trace:t"},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/ledger/events:batch"
        assert json.loads(request.content)["events"] == events
        return httpx.Response(
            201,
            json={"accepted": 3, "atomic": True, "totals": {"b|trace:t|lifetime": 5}},
        )

    result = _client(handler).apply_events(events)
    assert result.accepted == 3 and result.atomic is True
    assert result.totals == {"b|trace:t|lifetime": 5}
    assert result.halted is False


def test_apply_events_with_nothing_makes_no_request():
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("no request expected")

    assert _client(handler).apply_events([]).accepted == 0


def test_apply_events_is_attempted_once_and_never_retried():
    """Events are not deduplicated by the plane, so an unknown outcome is not retried."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ReadTimeout("lost response", request=request)

    with pytest.raises(ControlPlaneUnavailable):
        _client(handler).apply_events([{"kind": "halt_clear", "trace_id": "t"}])
    assert calls["n"] == 1


def test_unknown_event_kind_is_a_client_error():
    client = _client(lambda r: httpx.Response(400, json={"detail": "unknown kind 'step'"}))
    with pytest.raises(ControlPlaneError) as caught:
        client.apply_events([{"kind": "step", "trace_id": "t"}])  # type: ignore[typeddict-item]
    assert caught.value.status_code == 400
    assert "unknown kind" in str(caught.value)


def test_halt_mark_status_and_clear():
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        if request.method == "GET":
            return httpx.Response(200, json={"halted": True, "halt_reason": "cap"})
        return httpx.Response(200, json={"halted": request.method == "POST"})

    client = _client(handler)
    client.mark_halted("t", "cap")
    status = client.halt_status("t")
    client.clear_halt("t")
    assert status.halted is True and status.reason == "cap"
    assert seen == [
        ("POST", "/v1/ledger/traces/t/halt"),
        ("GET", "/v1/ledger/traces/t/halt"),
        ("DELETE", "/v1/ledger/traces/t/halt"),
    ]


def test_traces_passes_filters():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["halted_only"] == "true"
        assert request.url.params["limit"] == "5"
        return httpx.Response(200, json={"traces": [{"trace_id": "t"}]})

    assert _client(handler).traces(halted_only=True, limit=5) == [{"trace_id": "t"}]


def test_from_env(monkeypatch):
    monkeypatch.delenv("CONTROL_PLANE_URL", raising=False)
    with pytest.raises(ControlPlaneError):
        ControlPlaneClient.from_env()
    monkeypatch.setenv("CONTROL_PLANE_URL", "http://plane:8000/")
    monkeypatch.setenv("CONTROL_PLANE_API_KEY", "secret")
    client = ControlPlaneClient.from_env()
    assert client.base_url == "http://plane:8000"
    client.close()

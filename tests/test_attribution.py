"""Attribution: dims merge, attribution builder, fail-closed registration lookup."""

from __future__ import annotations

import pytest

from tokenops.control.attribution import (
    _build_attribution,
    merge_hop_dims,
    require_hop,
)
from tokenops.control.context import SpanContext, clear, run_scope
from tokenops.control.integration import step_to_observation
from tokenops.control.models import HopAttribution, NoGovernanceScopeError


def test_build_attribution_maps_service_and_user_dims():
    reg = HopAttribution(
        trace_id="r1", intent="f500", user_dims={"user_id": "alice", "Country": "US"}
    )
    attr = _build_attribution(reg, service="research")
    assert attr.trace_id == "r1"
    assert attr.agent == "research"
    assert attr.user == "alice"
    assert attr.tags["intent"] == "f500"
    assert attr.tags["Country"] == "US"


def test_user_defaults_to_unknown_without_a_user_dim():
    attr = _build_attribution(HopAttribution(trace_id="r1"), service="research")
    assert attr.user == "unknown"


def test_agent_dims_win_over_the_payload_and_payload_fills_the_allow_list():
    dims = merge_hop_dims(
        {"user_id": "agent-user", "Country": "US"},
        {"user_id": "payload-user", "user": "u2", "other": "ignored"},
    )
    assert dims["user_id"] == "agent-user"
    assert dims["user"] == "u2"
    assert dims["Country"] == "US"
    assert "other" not in dims


def test_payload_user_dims_fill_gaps_only_for_allow_listed_keys():
    dims = merge_hop_dims(None, {"user_dims": {"user_id": "p", "secret": "x"}})
    assert dims == {"user_id": "p"}


def test_require_registration_fails_closed_outside_a_scope():
    clear()
    with pytest.raises(NoGovernanceScopeError):
        require_hop()


def test_require_registration_inside_a_scope():
    clear()
    reg = HopAttribution(trace_id="r1", intent="demo")
    with run_scope(reg, SpanContext(span_id="s1", service="research")):
        assert require_hop().trace_id == "r1"
    clear()


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

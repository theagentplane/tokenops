"""Browser agent drives the real bench-site through the governor (offline, scripted brain)."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from tokenops.agents.browser.native.agent import NativeBrowserAgent
from tokenops.agents.browser.native.demo import demo_browser_complete
from tokenops.agents.browser.native.tools import HttpxBrowser
from tokenops.bench_site.app import build_app
from tokenops.chronicle import reset_session
from tokenops.config.schema import AgentServerConfig
from tokenops.control import ApplyControls, Governor, Ledger, build_attribution, wrap_complete
from tokenops.control.context import SpanContext, governance_scope, run_scope
from tokenops.control.models import RunRegistration
from tokenops.control.policies import progress_guard, tool_output_cap
from conftest import toy_price


def _backend():
    site = TestClient(build_app())
    return HttpxBrowser("http://site", fetch=lambda path: site.get(path).text)


def test_browser_agent_hits_traps_through_governor():
    ledger = Ledger(price=toy_price)
    controls = ApplyControls()
    gov = Governor(ledger, controls)
    gov.register(*tool_output_cap.build(cap_tokens=2000))          # huge DOM tool crossing
    gov.register(*progress_guard.build(window=8, repeats=3, max_corrections=99))  # observe only

    reg = RunRegistration(run_id="b1", intent="demo", user_dims={"user_id": "alice"})
    attr = build_attribution(reg, service="browser")
    ledger.open_run("b1")

    governed = wrap_complete(gov, controls, attr, provider="openai", model="gpt-4o-mini",
                             dispatch=demo_browser_complete(), service="browser")
    agent = NativeBrowserAgent(AgentServerConfig(max_steps=20, provider="openai", model="gpt-4o-mini"))

    reset_session().begin_trace("b1")
    with run_scope(reg, SpanContext(span_id="s", service="browser")):
        with governance_scope(gov, attr, provider="openai", model="gpt-4o-mini"):
            result = agent.run("gather the report and latest feed", backend=_backend(),
                               complete_fn=governed, service="browser")

    window = gov.ledger.window("b1")
    llm = [s for s in window if s.node_type == "llm"]
    tools = [s for s in window if s.node_type == "tool"]
    assert llm and tools
    # the /huge page produced a much larger llm input than a small page
    assert max(s.usage.input for s in llm if s.usage) > 5000
    # the recursive loop produced repeated navigate/click crossings
    assert sum(1 for s in tools if s.boundary_id == "click") >= 3
    # the trivial extract pulled the phone number
    assert "+1-555-0142" in result

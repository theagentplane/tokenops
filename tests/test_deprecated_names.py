"""1.x keeps the 1.0 names as aliases of the renamed ones."""

from __future__ import annotations

from tokenops import control
from tokenops.control import context, models


def test_registration_names_are_aliases_of_the_hop_names():
    assert control.RunRegistration is control.HopAttribution is models.HopAttribution
    assert control.RunNotRegisteredError is control.NoGovernanceScopeError
    assert control.require_registration is control.require_hop
    assert control.merge_registration_dims is control.merge_hop_dims
    assert context.current_registration is context.current_hop
    assert context.bind_registration is context.bind_hop


def test_bound_handles_keep_the_registration_property():
    hop = models.HopAttribution(trace_id="a" * 32, intent="x")
    bound = context.BoundRun(hop=hop, span=context.SpanContext(span_id="s", service="svc"))
    assert bound.registration is hop

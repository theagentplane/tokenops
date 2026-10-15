"""1.x keeps the 1.0 names and import paths as aliases of the moved or renamed ones."""

from __future__ import annotations

import importlib
import sys
import warnings

import pytest

from tokenops import capabilities, framework, interfaces
from tokenops.framework import context, models

MOVED_MODULES = {
    "tokenops.control.attribution": "tokenops.framework.attribution",
    "tokenops.control.boundary": "tokenops.framework.boundary",
    "tokenops.control.config": "tokenops.framework.config",
    "tokenops.control.context": "tokenops.framework.context",
    "tokenops.control.core": "tokenops.framework.core",
    "tokenops.control.engine": "tokenops.framework.engine",
    "tokenops.control.ledger": "tokenops.framework.ledger",
    "tokenops.control.models": "tokenops.framework.models",
    "tokenops.control.policy_labels": "tokenops.framework.policy_labels",
    "tokenops.control.pricing": "tokenops.framework.pricing",
    "tokenops.control.request_context": "tokenops.framework.request_context",
    "tokenops.control.usage": "tokenops.framework.usage",
    "tokenops.control.policies._util": "tokenops.framework.policies._util",
    "tokenops.control.policies.cost_budget": "tokenops.framework.policies.cost_budget",
    "tokenops.control.crossing": "tokenops.capabilities.crossing",
    "tokenops.control.integration": "tokenops.capabilities.integration",
    "tokenops.control.ledger_writers": "tokenops.capabilities.ledger_writers",
    "tokenops.control.run": "tokenops.capabilities.run",
    "tokenops.control.http": "tokenops.interfaces.http",
    "tokenops.control.instrument": "tokenops.interfaces.instrument",
}


@pytest.mark.parametrize("old,new", sorted(MOVED_MODULES.items()))
def test_an_old_module_path_is_the_same_module_as_the_new_one(old: str, new: str) -> None:
    sys.modules.pop(old, None)
    with pytest.warns(DeprecationWarning, match="moved to"):
        old_module = importlib.import_module(old)
    assert old_module is importlib.import_module(new)


def test_the_old_package_still_exports_the_same_objects() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        control = importlib.import_module("tokenops.control")
    for name in control.__all__:
        home = next(
            (
                getattr(layer, name)
                for layer in (framework, capabilities, interfaces)
                if name in layer.__all__
            ),
            None,
        )
        if home is not None:
            assert getattr(control, name) is home, name


def test_registration_names_are_aliases_of_the_hop_names():
    assert framework.RunRegistration is framework.HopAttribution is models.HopAttribution
    assert framework.RunNotRegisteredError is framework.NoGovernanceScopeError
    assert framework.require_registration is framework.require_hop
    assert framework.merge_registration_dims is framework.merge_hop_dims
    assert context.current_registration is context.current_hop
    assert context.bind_registration is context.bind_hop


def test_bound_handles_keep_the_registration_property():
    hop = models.HopAttribution(trace_id="a" * 32, intent="x")
    bound = context.BoundRun(hop=hop, span=context.SpanContext(span_id="s", service="svc"))
    assert bound.registration is hop

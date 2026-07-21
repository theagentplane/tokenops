"""HTTP propagation headers from ambient TokenOps context."""

from __future__ import annotations

from tokenops.control.attribution import begin_entry_run
from tokenops.control.context import (
    PARENT_SPAN_ID_HEADER,
    RUN_ID_HEADER,
    clear,
    run_scope,
)
from tokenops.control.propagate import merge_propagation_headers, propagation_headers
from tokenops.control.store import Store


def test_propagation_empty_outside_scope():
    clear()
    assert propagation_headers() == {}
    assert merge_propagation_headers({"X-Custom": "1"}) == {"X-Custom": "1"}


def test_propagation_injects_run_and_parent_span(tmp_path):
    store = Store(str(tmp_path / "p.db"), auto_seed=False)
    clear()
    bound = begin_entry_run(
        store,
        headers={},
        payload={"intent": "demo"},
        service="planner",
        run_id="run-prop",
    )
    with run_scope(bound.registration, bound.span):
        headers = propagation_headers()
        assert headers[RUN_ID_HEADER] == "run-prop"
        assert headers[PARENT_SPAN_ID_HEADER] == bound.span.span_id
        # Explicit wins over ambient
        merged = merge_propagation_headers({RUN_ID_HEADER: "run-override"})
        assert merged[RUN_ID_HEADER] == "run-override"
        assert merged[PARENT_SPAN_ID_HEADER] == bound.span.span_id
    clear()
    store.close()

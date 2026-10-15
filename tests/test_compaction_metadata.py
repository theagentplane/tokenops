"""context_compaction savings are recorded as envelope metadata (the plane stores none)."""

from __future__ import annotations

from conftest import toy_price
from tokenops.control import ApplyControls, Governor, Ledger, wrap_complete
from tokenops.control.attribution import _build_attribution
from tokenops.control.context import SpanContext, _governance_scope, run_scope
from tokenops.control.models import RunRegistration
from tokenops.control.policies import context_compaction
from tokenops.providers.types import ModelResponse


def _run(chronicle_envelopes, *, ctx_max: int):
    controls = ApplyControls()
    gov = Governor(Ledger(price=toy_price), controls)
    gov.register(*context_compaction.build(ctx_max=ctx_max))
    reg = RunRegistration(trace_id="a" * 32, intent="t", user_dims={"user_id": "alice"})
    attr = _build_attribution(reg, service="research")
    gov.ledger.open_run(reg.trace_id)

    def dispatch(provider, model, messages, max_output_tokens=None, **kw):
        return ModelResponse(content="ok", input_tokens=80, output_tokens=20)

    governed = wrap_complete(
        gov,
        controls,
        attr,
        provider="openai",
        model="gpt-4o-mini",
        dispatch=dispatch,
        service="research",
    )
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "dup"},
        {"role": "user", "content": "dup"},
        {"role": "user", "content": "unique"},
    ]
    with run_scope(reg, SpanContext(span_id="s1", service="research")):
        with _governance_scope(gov, attr, provider="openai", model="gpt-4o-mini"):
            governed("openai", "gpt-4o-mini", messages)
    return chronicle_envelopes


def test_compaction_savings_are_on_the_envelope(chronicle_envelopes):
    envelopes = _run(chronicle_envelopes, ctx_max=10)  # tiny context: always compacts
    llm = [e for e in envelopes if e.name == "research.chat"]
    assert len(llm) == 1
    meta = llm[0].metadata
    before = meta["tokenops.compaction_tokens_before"]
    after = meta["tokenops.compaction_tokens_after"]
    saved = meta["tokenops.compaction_tokens_saved"]
    assert before > 0 and after > 0
    assert saved == before - after


def test_no_compaction_metadata_when_nothing_was_compacted(chronicle_envelopes):
    envelopes = _run(chronicle_envelopes, ctx_max=1_000_000)
    llm = [e for e in envelopes if e.name == "research.chat"]
    assert len(llm) == 1
    assert not any(key.startswith("tokenops.") for key in llm[0].metadata)

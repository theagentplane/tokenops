"""Provider usage reaches pricing exactly once, in disjoint token buckets."""

from types import SimpleNamespace as NS
from unittest.mock import patch

from tokenops.control.boundary import observation_from_crossing
from tokenops.control.context import SpanContext, run_scope
from tokenops.control.core import Attribution, Usage
from tokenops.control.integration import step_to_observation
from tokenops.control.models import RunRegistration
from tokenops.control.pricing import Rate, build_price_book
from tokenops.providers import anthropic as ant
from tokenops.providers import openai as oa
from tokenops.providers.types import ModelResponse

PROMPT, CACHED, OUTPUT = 814835, 677898, 17947
PRICE = build_price_book({"fixture": Rate(500000, 3000000, cached=50000)})


def crossing(result, provider="openai"):
    with run_scope(RunRegistration(run_id="offline-137"), SpanContext(span_id="s", service="test")):
        return observation_from_crossing(
            boundary_id="test.chat",
            kind="llm",
            service="test",
            input_state={},
            result=result,
            provider=provider,
            model="fixture",
        ).usage


def oa_response():
    return NS(
        usage=NS(
            prompt_tokens=PROMPT,
            completion_tokens=OUTPUT,
            prompt_tokens_details=NS(cached_tokens=CACHED),
            completion_tokens_details=NS(reasoning_tokens=100),
        ),
        choices=[NS(message=NS(content="offline"))],
    )


def ant_response():
    return NS(
        usage=NS(
            input_tokens=PROMPT - CACHED,
            output_tokens=OUTPUT,
            cache_read_input_tokens=CACHED,
            cache_creation_input_tokens=0,
        ),
        content=[NS(type="text", text="offline")],
    )


def test_openai_boundary_preserves_cache_and_reasoning():
    u = crossing(oa_response())
    assert u == Usage(input=136937, output=17847, cached=677898, reasoning=100)


def test_responses_shape_preserves_cache_and_reasoning():
    u = crossing(
        NS(
            usage=NS(
                input_tokens=1000,
                output_tokens=200,
                input_tokens_details=NS(cached_tokens=800),
                output_tokens_details=NS(reasoning_tokens=150),
            )
        )
    )
    assert u == Usage(input=200, output=50, cached=800, reasoning=150)


def test_anthropic_boundary_prices_native_disjoint_cache_reads():
    u = crossing(ant_response(), "anthropic")
    assert u == Usage(input=136937, output=17947, cached=677898)
    assert PRICE("anthropic", "fixture", u) == 156204


def test_flat_fallback_normalizes_inclusive_fields():
    assert crossing(
        NS(input_tokens=1000, output_tokens=200, cached_tokens=800, reasoning_tokens=150)
    ) == Usage(input=200, output=50, cached=800, reasoning=150)


def test_agent_step_normalizes_inclusive_fields():
    step = NS(
        action="model",
        tokens=NS(input_tokens=1000, output_tokens=200, cached_tokens=800, reasoning_tokens=150),
    )
    u = step_to_observation(
        step, Attribution(user="test", agent="test", run_id="offline"), ts=0
    ).usage
    assert u == Usage(input=200, output=50, cached=800, reasoning=150)


def test_bundled_openai_adapter_preserves_details_through_boundary():
    client = NS(chat=NS(completions=NS(create=lambda **kw: oa_response())))
    with patch.object(oa, "OpenAI", return_value=client):
        result = oa.chat("fixture", [])
    assert result.cached_tokens == 677898
    assert crossing(result) == Usage(input=136937, output=17847, cached=677898, reasoning=100)


def test_bundled_anthropic_adapter_preserves_details_through_boundary():
    client = NS(messages=NS(create=lambda **kw: ant_response()))
    with patch.object(ant.anthropic, "Anthropic", return_value=client):
        result = ant.messages("fixture", [])
    assert result.input_tokens == 814835
    assert result.cached_tokens == 677898
    assert crossing(result, "anthropic") == Usage(input=136937, output=17947, cached=677898)


def test_legacy_two_count_response_control():
    assert crossing(ModelResponse("legacy", 12, 4)) == Usage(input=12, output=4)


def test_high_cache_fixture_is_priced_once():
    assert PRICE("openai", "fixture", crossing(oa_response())) == 156204


def test_details_can_be_missing_or_none():
    for details in ({}, {"prompt_tokens_details": None, "completion_tokens_details": None}):
        assert crossing(NS(usage=NS(prompt_tokens=12, completion_tokens=4, **details))) == Usage(
            input=12, output=4
        )
    assert crossing(NS(usage=None)) == Usage()


def test_zero_totals_do_not_fall_through_to_another_alias():
    assert (
        crossing(
            NS(usage=NS(prompt_tokens=0, input_tokens=99, completion_tokens=0, output_tokens=99))
        )
        == Usage()
    )


def test_reasoning_is_not_double_billed():
    price = build_price_book({"x": Rate(0, 1000000, reasoning=2000000)})
    usage = crossing(NS(input_tokens=0, output_tokens=200, reasoning_tokens=150))
    assert usage == Usage(output=50, reasoning=150)
    assert price("", "x", usage) == 350


def test_context_trend_includes_cached_prompt_tokens():
    from tokenops.control.core import CallRequest
    from tokenops.control.policies.context_compaction import ContextCompactionDetector

    request = CallRequest(
        attr=Attribution(user="t", agent="t", run_id="t"),
        provider="fixture",
        model="fixture",
        estimated_input_tokens=6000,
    )
    steps = [NS(node_type="llm", usage=Usage(input=1000, cached=n)) for n in (3000, 5000, 7000)]
    signal = ContextCompactionDetector(10000).pre_call(request, NS(recent=lambda *args: steps))
    assert signal is not None
    assert signal.evidence["rising"] is True

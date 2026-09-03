"""Several policies can act on one call. Their actions must merge, not fight.

``Governor._enforce`` sorts signals by severity and then applies every one of them,
so a single ``observe`` pass can hand ``ApplyControls`` a MUTATE from ``cost_guard``
and another from ``pre_call_worst_case``. Which lands last is decided by severity
rank and then detector registration order, neither of which a user controls, so the
connector has to merge deterministically instead of overwriting.
"""

from __future__ import annotations

import pytest

from tokenops.control import ApplyControls
from tokenops.control.core import Action, ActionKind


def mutate(**kw) -> Action:
    return Action(kind=ActionKind.MUTATE, run_id="r", **kw)


def inject(message: str, **kw) -> Action:
    return Action(kind=ActionKind.INJECT, run_id="r", inject_message=message, **kw)


class TestOutputCapOnlyTightens:
    """A later, looser cap must not undo an earlier, tighter one."""

    def test_looser_cap_applied_second_does_not_widen(self):
        c = ApplyControls()
        c.apply(mutate(max_output_tokens=256))  # cost_guard tightening under pressure
        c.apply(mutate(max_output_tokens=1024))  # pre_call_worst_case default cap
        assert c.call.max_output_tokens == 256

    def test_tighter_cap_applied_second_does_tighten(self):
        c = ApplyControls()
        c.apply(mutate(max_output_tokens=1024))
        c.apply(mutate(max_output_tokens=256))
        assert c.call.max_output_tokens == 256

    def test_order_does_not_change_the_outcome(self):
        """The whole point: the result cannot depend on registration order."""
        caps = [512, 128, 2048, 256]
        first = ApplyControls()
        for cap in caps:
            first.apply(mutate(max_output_tokens=cap))
        second = ApplyControls()
        for cap in reversed(caps):
            second.apply(mutate(max_output_tokens=cap))
        assert first.call.max_output_tokens == second.call.max_output_tokens == 128

    def test_first_cap_still_sets_the_value(self):
        c = ApplyControls()
        c.apply(mutate(max_output_tokens=700))
        assert c.call.max_output_tokens == 700

    def test_begin_call_clears_the_cap_for_the_next_call(self):
        c = ApplyControls()
        c.apply(mutate(max_output_tokens=128))
        c.begin_call()
        c.apply(mutate(max_output_tokens=4096))
        assert c.call.max_output_tokens == 4096


class TestCarryIsBounded:
    """cost_guard fires because spend is high. Steer messages must not pile up."""

    def test_duplicate_directives_are_not_repeated(self):
        c = ApplyControls()
        c.apply(inject("BUDGET PRESSURE: keep responses minimal."))
        c.apply(inject("BUDGET PRESSURE: keep responses minimal."))
        assert c.carry == ["BUDGET PRESSURE: keep responses minimal."]
        assert c.dropped_carry == 0

    def test_carry_stops_at_max_carry_and_counts_drops(self):
        c = ApplyControls(max_carry=2)
        for i in range(5):
            c.apply(inject(f"directive {i}"))
        assert c.carry == ["directive 0", "directive 1"]
        assert c.dropped_carry == 3

    def test_three_policies_in_one_pass_all_fit_by_default(self):
        """The realistic case: cost_guard + tool_output_cap + progress_guard."""
        c = ApplyControls()
        c.apply(inject("BUDGET PRESSURE: keep responses minimal."))
        c.apply(inject("NO PROGRESS DETECTED on 'search'."))
        c.apply(mutate(inject_message="CONTEXT COMPACTED: older turns summarized."))
        assert len(c.carry) == 3
        assert c.dropped_carry == 0

    def test_begin_call_resets_the_drop_counter(self):
        c = ApplyControls(max_carry=1)
        c.apply(inject("a"))
        c.apply(inject("b"))
        assert c.dropped_carry == 1
        c.begin_call()
        assert c.dropped_carry == 0

    def test_tool_result_override_is_not_a_carry_message(self):
        """A deep INJECT replaces the tool result; it must not spend carry budget."""
        c = ApplyControls(max_carry=1)
        c.apply(inject("OFFLOADED: handle=store://abc", replace_tool_result=True))
        c.apply(inject("BUDGET PRESSURE: keep responses minimal."))
        assert c.tool_result_override == "OFFLOADED: handle=store://abc"
        assert c.carry == ["BUDGET PRESSURE: keep responses minimal."]
        assert c.dropped_carry == 0


def test_model_downgrade_and_cap_merge_together():
    """The end-to-end shape of one observe pass with several policies firing."""
    c = ApplyControls()
    c.apply(inject("BUDGET PRESSURE: keep responses minimal."))
    c.apply(mutate(downgrade_to="gpt-4o-mini", max_output_tokens=256))
    c.apply(mutate(max_output_tokens=1024))
    assert c.call.model_override == "gpt-4o-mini"
    assert c.call.max_output_tokens == 256
    assert c.carry == ["BUDGET PRESSURE: keep responses minimal."]
    assert len(c.event_log) == 3


@pytest.mark.parametrize("cap", [1, 16, 4096])
def test_a_single_cap_is_always_honoured(cap):
    c = ApplyControls()
    c.apply(mutate(max_output_tokens=cap))
    assert c.call.max_output_tokens == cap

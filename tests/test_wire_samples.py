"""Blocking guard: every ``LedgerEvent`` field is enrolled in the wire-compat samples.

Deterministic and plane-free. Adding a field to ``LedgerEvent`` without a sample and an
observer fails here, which is what turns "the SDK sends a new field" into "the compat
suite checks the plane keeps it" — the step that was missing when ``step.compaction``
shipped (control-plane#18).
"""

from __future__ import annotations

from tokenops.control.ledger_backend import LedgerEvent
from wire_samples import ENVELOPE, OBSERVERS, SAMPLES, UNOBSERVABLE


def _sampled_fields() -> set[str]:
    return {f for ev in SAMPLES.values() for f in ev}


def test_every_ledger_event_field_has_a_sample():
    missing = set(LedgerEvent.__annotations__) - _sampled_fields()
    assert not missing, f"add {sorted(missing)} to tests/wire_samples.py SAMPLES"


def test_samples_use_only_declared_fields():
    extra = _sampled_fields() - set(LedgerEvent.__annotations__)
    assert not extra, f"samples carry fields LedgerEvent does not declare: {sorted(extra)}"


def test_every_sampled_field_is_observed_or_declared_unobservable():
    enrolled = set(OBSERVERS) | set(UNOBSERVABLE)
    needed = {(kind, f) for kind, ev in SAMPLES.items() for f in ev if f not in ENVELOPE}
    assert needed <= enrolled, f"no observer for {sorted(needed - enrolled)}"
    stale = enrolled - needed
    assert not stale, f"observers for fields no sample sends: {sorted(stale)}"

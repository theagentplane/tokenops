"""Wire-schema compatibility: does the plane keep every field the SDK sends?

NON-BLOCKING. Marked ``compat``, excluded from the default run, and executed by its own
CI job with ``continue-on-error``. A failure means the installed control plane is older
than, or has diverged from, what this SDK emits — useful to know, not a reason to block
an SDK change.

One case per (event kind, field), so a failure names the exact field the plane dropped:

    FAILED ...::test_plane_keeps_field[step.compaction]

Run locally against whatever plane is installed:

    python -m pytest -m compat tests/compat -q
"""

from __future__ import annotations

import pytest

from wire_samples import ENVELOPE, OBSERVERS, SAMPLES, UNOBSERVABLE

pytestmark = pytest.mark.compat

CASES = [(kind, f) for kind, ev in SAMPLES.items() for f in ev if f not in ENVELOPE]


def _send(backend, kind: str) -> dict:
    """Apply the sample for *kind* (``complete`` needs an admit first)."""
    if kind == "complete":
        backend.apply_events([SAMPLES["admit"]])
    ev = SAMPLES[kind]
    res = backend.apply_events([ev])
    assert res.accepted == 1, f"plane did not accept the {kind} sample: {res}"
    return ev


@pytest.mark.parametrize(("kind", "field"), CASES, ids=[f"{k}.{f}" for k, f in CASES])
def test_plane_keeps_field(plane_backend, kind, field):
    if (kind, field) in UNOBSERVABLE:
        pytest.skip(f"unobservable: {UNOBSERVABLE[(kind, field)]}")
    ev = _send(plane_backend, kind)
    expected, actual = OBSERVERS[(kind, field)](plane_backend, ev)
    assert actual == expected, (
        f"plane accepted {kind}.{field}={expected!r} (201) but reports {actual!r}: "
        "it is being dropped or altered. See docs/testing.md, cross-repo section."
    )

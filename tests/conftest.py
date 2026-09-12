"""Shared test helpers for the control plane.

Two tools that keep policy tests independent (one failure → one unit):

* ``FakeView`` — a ``LedgerView`` whose reads are fixed by constructor kwargs, so a
  detector can be tested with zero real ledger and zero other policies.
* ``CollectingControls`` — an OUT connector that records every Action (and still raises
  on HALT), so a corrective policy's MUTATE/INJECT can be asserted through the Governor
  before the real provider wrap exists.
"""

from __future__ import annotations

import os

# Tests expect an empty governance store unless they seed explicitly.
os.environ.setdefault("TOKENOPS_SKIP_GOVERNANCE_SEED", "1")

from dataclasses import dataclass, field

from tokenops.control.core import Action, ActionKind, Attribution, BoundaryStep, Halt, Usage


def toy_price(provider: str, model: str, usage: Usage) -> int:
    """micro-USD: 10/input token, 30/output token. Fail closed on unknown model."""
    if model not in {"gpt-4o-mini", "claude-sonnet-4-6"}:
        raise ValueError(f"unknown model {model!r}")
    return usage.input * 10 + usage.output * 30


def make_attr(run_id: str = "run-1", **kw) -> Attribution:
    base = dict(user="alice", agent="research", run_id=run_id)
    base.update(kw)
    return Attribution(**base)


def make_step(
    step: int = 1, *, node_type="llm", boundary_id="research.chat", cum=0, **kw
) -> BoundaryStep:
    return BoundaryStep(
        step=step,
        ts=float(step),
        node_type=node_type,
        boundary_id=boundary_id,
        cum_spent_micros=cum,
        **kw,
    )


@dataclass
class FakeView:
    """A LedgerView with reads pinned by constructor kwargs. Override only what a test needs."""

    _cost: int = 0
    _steps: int = 0
    _halted: bool = False
    _budget_left: int = 1_000_000
    _inflight: int = 0
    _velocity: float = 0.0
    _recent: list = field(default_factory=list)
    _window: list = field(default_factory=list)

    def cost_micros(self, run_id):
        return self._cost

    def step_count(self, run_id):
        return self._steps

    def is_halted(self, run_id):
        return self._halted

    def budget_left(self, budget_id, segment_key, period="lifetime"):
        return self._budget_left

    def inflight(self, segment_key):
        return self._inflight

    def velocity(self, run_id, m):
        return self._velocity

    def recent(self, run_id, n):
        return self._recent[-n:]

    def window(self, run_id):
        return self._window


@dataclass
class CollectingControls:
    """OUT connector that records actions. Still raises Halt on HALT (so kill-switch and
    sticky behaviour are exercised), but records corrective kinds for assertion."""

    actions: list = field(default_factory=list)

    def apply(self, action: Action) -> None:
        self.actions.append(action)
        if action.kind is ActionKind.HALT:
            raise Halt(action)

    def of_kind(self, kind: ActionKind):
        return [a for a in self.actions if a.kind is kind]


# --------------------------------------------------------------------------- #
# LedgerBackend fixtures (remote-only rewrite)                                 #
# --------------------------------------------------------------------------- #

import gc
import shutil
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def fake_backend():
    """In-memory FakeLedgerBackend — the unit-test backend."""
    from fakes import FakeLedgerBackend

    return FakeLedgerBackend()


@pytest.fixture
def plane_app_factory():
    """Build a real control_plane.app over a throwaway SQLite file.

    Skips the whole test when ``agentplane-control-plane`` (>= 0.2.0) is not installed
    — it is not a hard dev dep (not on PyPI yet); ``pip install -e ".[dev,contract]"``
    to run these. Yields a callable; every app it makes is torn down (connections
    closed before the temp dir is removed — open SQLite handles block unlink on Windows).
    """
    pytest.importorskip("control_plane", reason="install agentplane-control-plane>=0.2.0")
    made: list[tuple] = []

    def _make(**settings_kw):
        from control_plane.app import create_app
        from control_plane.envelope_store import EnvelopeStore
        from control_plane.settings import Settings
        from control_plane.store import SqliteStore

        td = tempfile.mkdtemp()
        db = str(Path(td) / "cp.db")
        store = SqliteStore(db, auto_seed=False)
        env = EnvelopeStore(db)
        app = create_app(store=store, envelopes=env, settings=Settings(db_path=db, **settings_kw))
        made.append((store, env, td))
        return app

    yield _make

    for store, env, td in made:
        store.close()
        env.close()
        gc.collect()
        shutil.rmtree(td, ignore_errors=True)


def _asgi_backend(app):
    """HttpLedgerBackend over an in-process control_plane.app.

    ``httpx.ASGITransport`` is async-only, so we drive the app through FastAPI's
    ``TestClient`` (a sync ``httpx.Client`` subclass backed by a portal).
    """
    from fastapi.testclient import TestClient

    from tokenops.control.ledger_backend import HttpLedgerBackend

    client = TestClient(app)
    return HttpLedgerBackend("http://testserver", client=client), client


@pytest.fixture
def http_backend(plane_app_factory):
    backend, client = _asgi_backend(plane_app_factory())
    try:
        yield backend
    finally:
        client.close()


@pytest.fixture
def live_plane_url(monkeypatch):
    """A real control plane on a real localhost TCP port, with ``CONTROL_PLANE_URL``
    pointed at it — for tests that must exercise ``ControlPlaneClient.from_env()``
    itself (no ``store=``/injected-client escape hatch reaches ``from_env()`` by
    design — tokenops#118: no env var may select a local ledger). An in-process ASGI
    app (``plane_app_factory``/``http_backend``) isn't reachable this way since
    ``from_env()`` builds its own plain ``httpx.Client(base_url=...)``.
    """
    pytest.importorskip("control_plane", reason="install agentplane-control-plane>=0.2.0")
    from tokenops.control.dev_plane import launch

    db = str(Path(tempfile.mkdtemp()) / "cp.db")
    plane = launch(db)
    monkeypatch.setenv("CONTROL_PLANE_URL", plane.url)
    monkeypatch.delenv("TOKENOPS_URL", raising=False)
    monkeypatch.delenv("TOKENOPS_CONTROL_PLANE_URL", raising=False)
    yield plane.url
    plane.stop()


@pytest.fixture(params=["fake", "http"])
def any_backend(request):
    """Parametrised over both backends — for the verified-fake contract suite.

    The ``fake`` param always runs; the ``http`` param resolves ``plane_app_factory``
    lazily, so it skips (not errors) when the real plane is not installed.
    """
    if request.param == "fake":
        from fakes import FakeLedgerBackend

        yield FakeLedgerBackend()
        return
    factory = request.getfixturevalue("plane_app_factory")
    backend, client = _asgi_backend(factory())
    try:
        yield backend
    finally:
        client.close()

"""Contract tests: the client against a real control plane 1.0 (in process, SQLite).

These pin the shapes the client relies on (``304``, the ``400`` for an unknown event kind,
``precheck`` after ``spent_add`` and a halt). They are skipped unless ``agentplane-control-plane``
1.0 or later is installed; CI runs them in a job that installs it from PyPI.
"""

from __future__ import annotations

import gc
import shutil
import socket
import tempfile
import threading
import time
from collections.abc import Iterator
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import httpx
import pytest

from tokenops.repositories import (
    ControlPlaneClient,
    ControlPlaneError,
    PrecheckRequest,
)

try:
    _PLANE_MAJOR = int(version("agentplane-control-plane").split(".")[0])
except PackageNotFoundError:  # pragma: no cover - environment dependent
    _PLANE_MAJOR = 0

pytestmark = pytest.mark.skipif(
    _PLANE_MAJOR < 1, reason="needs agentplane-control-plane>=1.0 installed"
)

API_KEY = "contract-key"
TRACE = "c" * 32


@pytest.fixture(scope="module")
def plane_url() -> Iterator[str]:
    import uvicorn
    from control_plane.api import create_app
    from control_plane.settings import Settings

    workdir = tempfile.mkdtemp(prefix="tokenops-contract-")
    url = f"sqlite:///{(Path(workdir) / 'plane.db').as_posix()}"
    settings = Settings(
        database_url=url,
        api_keys=f"{API_KEY}:contract:ingest+read+admin",
        seed_on_start=False,
    )
    app = create_app(settings)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(app, log_level="warning", lifespan="off", access_log=False)
    )
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("the control plane did not start")
        time.sleep(0.02)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()
        app.state.cp.engine.dispose()
        gc.collect()
        shutil.rmtree(workdir, ignore_errors=True)


@pytest.fixture()
def client(plane_url: str) -> Iterator[ControlPlaneClient]:
    with ControlPlaneClient(plane_url, api_key=API_KEY) as c:
        yield c


def _admin(plane_url: str) -> httpx.Client:
    return httpx.Client(
        base_url=plane_url, headers={"Authorization": f"Bearer {API_KEY}"}, timeout=10
    )


def test_governance_is_pulled_with_an_etag_and_revalidated_with_304(
    plane_url: str, client: ControlPlaneClient
):
    with _admin(plane_url) as admin:
        admin.put(
            "/v1/budgets",
            json={"id": "run_llm_cap", "limit_micros": 1000, "dimension": "trace"},
        ).raise_for_status()
        admin.put(
            "/v1/policies",
            json={
                "id": "cap",
                "template": "cost_budget",
                "budget_id": "run_llm_cap",
                "params": {"budget": "run_llm_cap"},
            },
        ).raise_for_status()

    first = client.governance("research")
    assert first.etag
    assert first.config["governance"]["budgets"][0]["id"] == "run_llm_cap"
    assert "cost_budget" in first.config["governance"]["policies"]

    revalidated = client.governance("research")
    assert revalidated.config == first.config
    assert revalidated.etag == first.etag
    assert revalidated.stale is False


def test_spent_add_is_visible_in_precheck_and_halt_round_trips(client: ControlPlaneClient):
    segment = f"trace:{TRACE}"
    target = {"budget_id": "run_llm_cap", "segment_key": segment, "period": "lifetime"}

    result = client.apply_events(
        [
            {"kind": "admit", "trace_id": TRACE, "segment_key": segment},
            {"kind": "spent_add", "trace_id": TRACE, "delta_micros": 700, "targets": [target]},
            {"kind": "complete", "trace_id": TRACE, "segment_key": segment},
        ]
    )
    assert result.accepted == 3

    state = client.precheck(
        PrecheckRequest(trace_id=TRACE, segment_keys=[segment], budgets=[target])
    )
    assert state.spent == {f"run_llm_cap|{segment}|lifetime": 700}
    assert state.inflight == {segment: 0}
    assert state.halted is False

    client.mark_halted(TRACE, "over budget")
    halted = client.halt_status(TRACE)
    assert halted.halted is True and halted.reason == "over budget"
    assert client.precheck(PrecheckRequest(trace_id=TRACE)).halted is True

    client.clear_halt(TRACE)
    assert client.halt_status(TRACE).halted is False


def test_unknown_event_kind_is_a_400(client: ControlPlaneClient):
    with pytest.raises(ControlPlaneError) as caught:
        client.apply_events([{"kind": "step", "trace_id": TRACE}])  # type: ignore[list-item]
    assert caught.value.status_code == 400


def test_events_are_not_deduplicated(client: ControlPlaneClient):
    trace = "d" * 32
    segment = f"trace:{trace}"
    target = {"budget_id": "dedupe_probe", "segment_key": segment, "period": "lifetime"}
    event = {"kind": "spent_add", "trace_id": trace, "delta_micros": 10, "targets": [target]}
    client.apply_events([event])  # type: ignore[list-item]
    client.apply_events([event])  # type: ignore[list-item]
    state = client.precheck(PrecheckRequest(trace_id=trace, budgets=[target]))
    assert state.spent == {f"dedupe_probe|{segment}|lifetime": 20}

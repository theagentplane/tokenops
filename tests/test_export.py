"""GET /v1/export — on-demand run-record export (CSV / JSON)."""

from __future__ import annotations

import csv
import io
import json

import pytest

from tokenops.control.models import RunRecord
from tokenops.control.store import Store


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "export.db"), auto_seed=False)


def _make_run(
    store: Store,
    *,
    run_id: str = "run-1",
    agent: str = "researcher",
    status: str = "completed",
    cost_micros: int = 1000,
    steps: int = 5,
    started_at: float = 100.0,
    ended_at: float | None = 200.0,
    dims: dict[str, str] | None = None,
    governance_events: list[dict] | None = None,
) -> RunRecord:
    rec = RunRecord(
        run_id=run_id,
        agent=agent,
        status=status,
        cost_micros=cost_micros,
        steps=steps,
        started_at=started_at,
        ended_at=ended_at,
        dims=dims or {},
        governance_events=governance_events or [],
    )
    created = store.create_run(rec)
    # governance_events is written via update_run (same as real server flow)
    if governance_events:
        store.update_run(run_id, governance_events=governance_events)
    return store.get_run(run_id) or created


# ------------------------------------------------------------------ #
# Store.export_runs unit tests                                        #
# ------------------------------------------------------------------ #


def test_export_runs_returns_all(store):
    _make_run(store, run_id="r1", agent="a", started_at=100)
    _make_run(store, run_id="r2", agent="b", started_at=200)
    result = store.export_runs()
    assert len(result) == 2


def test_export_runs_filters_from_at(store):
    _make_run(store, run_id="r1", started_at=100)
    _make_run(store, run_id="r2", started_at=200)
    result = store.export_runs(from_at=150)
    assert len(result) == 1
    assert result[0].run_id == "r2"


def test_export_runs_filters_to_at(store):
    _make_run(store, run_id="r1", started_at=100)
    _make_run(store, run_id="r2", started_at=200)
    result = store.export_runs(to_at=150)
    assert len(result) == 1
    assert result[0].run_id == "r1"


def test_export_runs_filters_agent(store):
    _make_run(store, run_id="r1", agent="researcher", started_at=100)
    _make_run(store, run_id="r2", agent="writer", started_at=200)
    result = store.export_runs(agent="writer")
    assert len(result) == 1
    assert result[0].run_id == "r2"


def test_export_runs_filters_status(store):
    _make_run(store, run_id="r1", status="completed", started_at=100)
    _make_run(store, run_id="r2", status="halted", started_at=200)
    result = store.export_runs(status="halted")
    assert len(result) == 1
    assert result[0].run_id == "r2"


def test_export_runs_filters_tenant(store):
    _make_run(store, run_id="r1", dims={"tenant": "acme"}, started_at=100)
    _make_run(store, run_id="r2", dims={"tenant": "globex"}, started_at=200)
    _make_run(store, run_id="r3", dims={}, started_at=300)
    result = store.export_runs(tenant="acme")
    assert len(result) == 1
    assert result[0].run_id == "r1"


def test_export_runs_combined_filters(store):
    _make_run(store, run_id="r1", agent="a", status="completed", started_at=100)
    _make_run(store, run_id="r2", agent="a", status="halted", started_at=200)
    _make_run(store, run_id="r3", agent="b", status="completed", started_at=300)
    result = store.export_runs(agent="a", status="completed")
    assert len(result) == 1
    assert result[0].run_id == "r1"


def test_export_runs_limit(store):
    for i in range(20):
        _make_run(store, run_id=f"r{i:02d}", started_at=float(i))
    result = store.export_runs(limit=5)
    assert len(result) == 5


def test_export_runs_empty(store):
    result = store.export_runs()
    assert result == []


def test_export_runs_preserves_governance_events(store):
    events = [{"kind": "halt", "reason": "budget exceeded", "policy": "cost_budget"}]
    _make_run(store, run_id="r1", governance_events=events)
    result = store.export_runs()
    assert result[0].governance_events == events


# ------------------------------------------------------------------ #
# GET /v1/export integration tests                                   #
# ------------------------------------------------------------------ #


def test_export_json_default(store, tmp_path):
    from fastapi.testclient import TestClient

    from tokenops.server.app import create_app

    _make_run(store, run_id="r1", agent="a", cost_micros=5000, started_at=100)
    app = create_app(store=store)
    client = TestClient(app)

    resp = client.get("/v1/export")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["run_id"] == "r1"
    assert data[0]["cost_micros"] == 5000
    assert resp.headers["X-Total-Count"] == "1"


def test_export_json_with_filters(store):
    from fastapi.testclient import TestClient

    from tokenops.server.app import create_app

    _make_run(store, run_id="r1", agent="a", started_at=100)
    _make_run(store, run_id="r2", agent="b", started_at=200)
    app = create_app(store=store)
    client = TestClient(app)

    resp = client.get("/v1/export?agent=b")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["run_id"] == "r2"


def test_export_csv(store):
    from fastapi.testclient import TestClient

    from tokenops.server.app import create_app

    _make_run(
        store,
        run_id="r1",
        agent="researcher",
        status="completed",
        cost_micros=12000,
        steps=8,
        started_at=100.0,
        ended_at=250.0,
        dims={"tenant": "acme"},
        governance_events=[{"kind": "mutate", "reason": "cap applied"}],
    )
    app = create_app(store=store)
    client = TestClient(app)

    resp = client.get("/v1/export?format=csv")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "text/csv; charset=utf-8"
    assert "export.csv" in resp.headers.get("content-disposition", "")

    reader = csv.reader(io.StringIO(resp.text))
    rows = list(reader)
    header = rows[0]
    assert "run_id" in header
    assert "cost_micros" in header
    assert "duration_s" in header
    assert "governance_events" in header
    body = rows[1]
    assert body[header.index("run_id")] == "r1"
    assert body[header.index("agent")] == "researcher"
    assert body[header.index("cost_micros")] == "12000"
    assert body[header.index("duration_s")] == "150.0"
    # dims and governance_events are JSON strings in CSV
    dims_val = json.loads(body[header.index("dims")])
    assert dims_val == {"tenant": "acme"}
    gov_val = json.loads(body[header.index("governance_events")])
    assert len(gov_val) == 1
    assert gov_val[0]["kind"] == "mutate"


def test_export_empty(store):
    from fastapi.testclient import TestClient

    from tokenops.server.app import create_app

    app = create_app(store=store)
    client = TestClient(app)

    resp = client.get("/v1/export")
    assert resp.status_code == 200
    assert resp.json() == []


def test_export_csv_empty(store):
    from fastapi.testclient import TestClient

    from tokenops.server.app import create_app

    app = create_app(store=store)
    client = TestClient(app)

    resp = client.get("/v1/export?format=csv")
    assert resp.status_code == 200
    reader = csv.reader(io.StringIO(resp.text))
    rows = list(reader)
    assert len(rows) == 1  # header only


def test_export_limit_capped(store):
    from fastapi.testclient import TestClient

    from tokenops.server.app import create_app

    for i in range(15):
        _make_run(store, run_id=f"r{i:02d}", started_at=float(i))
    app = create_app(store=store)
    client = TestClient(app)

    resp = client.get("/v1/export?limit=5")
    assert resp.status_code == 200
    assert len(resp.json()) == 5


# ------------------------------------------------------------------ #
# _coerce_epoch unit tests                                           #
# ------------------------------------------------------------------ #

from datetime import date, datetime

from tokenops.control.store import _coerce_epoch


def test_coerce_epoch_none():
    assert _coerce_epoch(None) is None


def test_coerce_epoch_float_passthrough():
    assert _coerce_epoch(1700000000.0) == 1700000000.0


def test_coerce_epoch_int_passthrough():
    assert _coerce_epoch(1700000000) == 1700000000.0


def test_coerce_epoch_date_string():
    result = _coerce_epoch("2026-09-19")
    expected = datetime(2026, 9, 19).timestamp()
    assert result == pytest.approx(expected)


def test_coerce_epoch_iso_datetime_string():
    result = _coerce_epoch("2026-09-19T12:00:00")
    expected = datetime(2026, 9, 19, 12, 0, 0).timestamp()
    assert result == pytest.approx(expected)


def test_coerce_epoch_date_object():
    result = _coerce_epoch(date(2026, 9, 19))
    expected = datetime(2026, 9, 19).timestamp()
    assert result == pytest.approx(expected)


def test_coerce_epoch_datetime_object():
    dt = datetime(2026, 9, 19, 15, 30)
    result = _coerce_epoch(dt)
    assert result == dt.timestamp()


# ------------------------------------------------------------------ #
# String-date filtering in export_runs (regression for type mismatch)#
# ------------------------------------------------------------------ #


def test_export_runs_filters_date_string(store):
    """Passing a date string instead of epoch float should still filter correctly."""
    # epoch 1600000000 ≈ 2020-09-13, epoch 1900000000 ≈ 2029-11-20
    _make_run(store, run_id="r1", started_at=1600000000.0)
    _make_run(store, run_id="r2", started_at=1900000000.0)
    # "2023-11-15" ≈ epoch 1699986600 — should include r2 but not r1
    result = store.export_runs(from_at="2023-11-15")
    assert len(result) == 1
    assert result[0].run_id == "r2"


def test_export_runs_filters_to_date_string(store):
    """Passing a to_at date string should filter correctly."""
    _make_run(store, run_id="r1", started_at=1600000000.0)
    _make_run(store, run_id="r2", started_at=1900000000.0)
    # "2023-11-15" ≈ epoch 1699986600 — should include r1 but not r2
    result = store.export_runs(to_at="2023-11-15")
    assert len(result) == 1
    assert result[0].run_id == "r1"

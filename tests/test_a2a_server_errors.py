"""The A2A example server must not echo exception text to callers."""

from __future__ import annotations

import logging

from fastapi.testclient import TestClient

from examples.a2a.server import create_a2a_app


def test_handler_error_returns_generic_500_and_logs_detail(caplog):
    async def handler(payload, headers):
        raise RuntimeError("secret /srv/db.sqlite path")

    app = create_a2a_app("t", "d", "http://x", [], handler)
    with caplog.at_level(logging.ERROR):
        res = TestClient(app).post("/v1/tasks", json={})

    assert res.status_code == 500
    assert res.json() == {"error": "internal error"}
    assert "secret" not in res.text
    assert "secret /srv/db.sqlite path" in caplog.text

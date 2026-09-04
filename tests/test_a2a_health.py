"""Tests for agent card fetching and health check timeouts."""

from __future__ import annotations

import httpx
import pytest
from examples.a2a import client
from examples.a2a.client import check_health, check_health_sync
from examples.a2a.server import fetch_agent_card, fetch_agent_card_sync


def test_fetch_agent_card_sync_default_timeout(monkeypatch):
    recorded_timeout = []

    class DummyClient:
        def __init__(self, timeout=None):
            recorded_timeout.append(timeout)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            return False

        def get(self, url):
            return httpx.Response(
                200, json={"name": "test-agent"}, request=httpx.Request("GET", url)
            )

    monkeypatch.setattr(httpx, "Client", DummyClient)
    res = fetch_agent_card_sync("http://localhost:8000")
    assert res == {"name": "test-agent"}
    assert recorded_timeout == [2.0]


def test_fetch_agent_card_sync_custom_timeout(monkeypatch):
    recorded_timeout = []

    class DummyClient:
        def __init__(self, timeout=None):
            recorded_timeout.append(timeout)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            return False

        def get(self, url):
            return httpx.Response(
                200, json={"name": "test-agent"}, request=httpx.Request("GET", url)
            )

    monkeypatch.setattr(httpx, "Client", DummyClient)
    res = fetch_agent_card_sync("http://localhost:8000", timeout=5.5)
    assert res == {"name": "test-agent"}
    assert recorded_timeout == [5.5]


@pytest.mark.asyncio
async def test_fetch_agent_card_async_default_timeout(monkeypatch):
    recorded_timeout = []

    class DummyAsyncClient:
        def __init__(self, timeout=None):
            recorded_timeout.append(timeout)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            return False

        async def get(self, url):
            return httpx.Response(
                200, json={"name": "test-agent"}, request=httpx.Request("GET", url)
            )

    monkeypatch.setattr(httpx, "AsyncClient", DummyAsyncClient)
    res = await fetch_agent_card("http://localhost:8000")
    assert res == {"name": "test-agent"}
    assert recorded_timeout == [2.0]


@pytest.mark.asyncio
async def test_fetch_agent_card_async_custom_timeout(monkeypatch):
    recorded_timeout = []

    class DummyAsyncClient:
        def __init__(self, timeout=None):
            recorded_timeout.append(timeout)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            return False

        async def get(self, url):
            return httpx.Response(
                200, json={"name": "test-agent"}, request=httpx.Request("GET", url)
            )

    monkeypatch.setattr(httpx, "AsyncClient", DummyAsyncClient)
    res = await fetch_agent_card("http://localhost:8000", timeout=4.0)
    assert res == {"name": "test-agent"}
    assert recorded_timeout == [4.0]


def test_check_health_sync_success_and_failure(monkeypatch):
    calls = []

    def fake_fetch(url, *, timeout=2.0):
        calls.append((url, timeout))
        if "offline" in url:
            raise httpx.ConnectError("Offline")
        return {"name": "ok"}

    monkeypatch.setattr(client, "fetch_agent_card_sync", fake_fetch)

    assert check_health_sync("http://localhost:8000") is True
    assert check_health_sync("http://offline:8000", timeout=1.5) is False
    assert calls == [("http://localhost:8000", 2.0), ("http://offline:8000", 1.5)]


@pytest.mark.asyncio
async def test_check_health_async_success_and_failure(monkeypatch):
    calls = []

    async def fake_fetch(url, *, timeout=2.0):
        calls.append((url, timeout))
        if "offline" in url:
            raise httpx.ConnectError("Offline")
        return {"name": "ok"}

    monkeypatch.setattr(client, "fetch_agent_card", fake_fetch)

    assert await check_health("http://localhost:8000") is True
    assert await check_health("http://offline:8000", timeout=1.2) is False
    assert calls == [("http://localhost:8000", 2.0), ("http://offline:8000", 1.2)]

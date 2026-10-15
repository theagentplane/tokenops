"""An in-memory control plane 1.0 for unit tests: ``httpx.MockTransport`` handler.

It implements only what TokenOps uses (governance, precheck, events:batch, halt, traces) with
the semantics the real plane documents. ``tests/contract`` runs the same scenarios against it
and against a real control plane, so it cannot drift silently.
"""

from __future__ import annotations

import json
import threading
from collections import defaultdict
from typing import Any

import httpx

from tokenops.repositories import ControlPlaneClient

_KINDS = {"spent_add", "admit", "complete", "halt_mark", "halt_clear"}


class FakePlane:
    """State and request handler of one fake control plane."""

    def __init__(self, *, governance: dict[str, Any] | None = None) -> None:
        self.governance: dict[str, dict[str, Any]] = {}
        self._default_governance = governance or {"governance": {"budgets": [], "policies": {}}}
        self.spent: dict[str, int] = defaultdict(int)
        self.inflight: dict[str, int] = defaultdict(int)
        self.halts: dict[str, str] = {}
        self.requests: list[httpx.Request] = []
        self.down = False
        self.version = 1
        self._lock = threading.Lock()

    # ---- test controls ----------------------------------------------------- #

    def set_governance(self, agent: str, config: dict[str, Any]) -> None:
        self.governance[agent] = config
        self.version += 1

    def client(self, **kwargs: Any) -> ControlPlaneClient:
        return ControlPlaneClient(
            "http://fake-plane", transport=httpx.MockTransport(self.handle), **kwargs
        )

    # ---- transport --------------------------------------------------------- #

    def handle(self, request: httpx.Request) -> httpx.Response:
        with self._lock:
            return self._handle(request)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.down:
            raise httpx.ConnectError("fake plane is down", request=request)
        path = request.url.path
        method = request.method
        if method == "GET" and path.startswith("/v1/governance/"):
            return self._governance(request, path.rsplit("/", 1)[1])
        if method == "POST" and path == "/v1/ledger/precheck":
            return self._precheck(json.loads(request.content))
        if method == "POST" and path == "/v1/ledger/events:batch":
            return self._events(json.loads(request.content)["events"])
        if path.startswith("/v1/ledger/traces/") and path.endswith("/halt"):
            trace_id = path.split("/")[4]
            if method == "GET":
                return httpx.Response(
                    200,
                    json={
                        "halted": trace_id in self.halts,
                        "halt_reason": self.halts.get(trace_id),
                    },
                )
            if method == "POST":
                self.halts[trace_id] = json.loads(request.content).get("reason", "")
                return httpx.Response(200, json={"halted": True})
            if method == "DELETE":
                self.halts.pop(trace_id, None)
                return httpx.Response(200, json={"halted": False})
        if method == "GET" and path == "/v1/ledger/traces":
            return httpx.Response(200, json={"traces": []})
        return httpx.Response(404, json={"detail": f"no fake route {method} {path}"})

    # ---- routes ------------------------------------------------------------ #

    def _governance(self, request: httpx.Request, agent: str) -> httpx.Response:
        body = self.governance.get(agent, self._default_governance)
        etag = f'"v{self.version}-{agent}"'
        if request.headers.get("If-None-Match") == etag:
            return httpx.Response(304)
        return httpx.Response(200, json=body, headers={"ETag": etag})

    def _precheck(self, body: dict[str, Any]) -> httpx.Response:
        want = body.get("want") or ["spent", "inflight", "halt"]
        out: dict[str, Any] = {"server_ts": 0.0}
        if "halt" in want:
            out["halted"] = body["trace_id"] in self.halts
            out["halt_reason"] = self.halts.get(body["trace_id"])
        if "spent" in want:
            out["spent"] = {
                f"{b['budget_id']}|{b['segment_key']}|{b.get('period', 'lifetime')}": self.spent[
                    f"{b['budget_id']}|{b['segment_key']}|{b.get('period', 'lifetime')}"
                ]
                for b in body.get("budgets") or []
            }
        if "inflight" in want:
            out["inflight"] = {s: self.inflight[s] for s in body.get("segment_keys") or []}
        return httpx.Response(200, json=out)

    def _events(self, events: list[dict[str, Any]]) -> httpx.Response:
        for event in events:
            if event.get("kind") not in _KINDS:
                return httpx.Response(400, json={"detail": f"unknown kind {event.get('kind')!r}"})
        totals: dict[str, int] = {}
        halted = False
        for event in events:
            kind = event["kind"]
            trace_id = event.get("trace_id", "")
            if kind == "spent_add":
                for t in event.get("targets") or []:
                    key = f"{t['budget_id']}|{t['segment_key']}|{t.get('period', 'lifetime')}"
                    self.spent[key] += int(event["delta_micros"])
                    totals[key] = self.spent[key]
            elif kind == "admit":
                self.inflight[event["segment_key"]] += 1
            elif kind == "complete":
                seg = event["segment_key"]
                self.inflight[seg] = max(0, self.inflight[seg] - 1)
            elif kind == "halt_mark":
                self.halts[trace_id] = event.get("reason", "")
            elif kind == "halt_clear":
                self.halts.pop(trace_id, None)
            halted = halted or trace_id in self.halts
        return httpx.Response(
            201, json={"accepted": len(events), "atomic": True, "totals": totals, "halted": halted}
        )

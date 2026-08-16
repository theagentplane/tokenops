"""SQLite store — the shared backbone for admin config + run history.

One ``tokenops.db`` is shared by four processes (research server, summarize server, the
Admin UI, the Dashboard UI), so they must agree on policies and runs. SQLite (WAL) gives
ACID + concurrent readers as a single inspectable, deletable file — no daemon, matching the
ledger's "swap the dict for a store" note.

The key method is :meth:`Store.governance_config_for`, which assembles exactly the dict
``control.config.build_governor`` already consumes — so the store drops in for static YAML
and ``build_governor`` is unchanged.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from typing import Sequence

from tokenops.control.config import _TEMPLATES
from tokenops.control.models import BudgetSpec, PolicyInstance, RunRecord, Segment

_SCHEMA = """
CREATE TABLE IF NOT EXISTS segments (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, dimension TEXT NOT NULL,
  tag_key TEXT, match_value TEXT
);
CREATE TABLE IF NOT EXISTS budgets (
  id TEXT PRIMARY KEY, limit_micros INTEGER, dimension TEXT NOT NULL,
  tag_key TEXT, period TEXT NOT NULL DEFAULT 'lifetime'
);
CREATE TABLE IF NOT EXISTS policy_instances (
  id TEXT PRIMARY KEY, template TEXT NOT NULL, params TEXT NOT NULL DEFAULT '{}',
  agent TEXT, budget_id TEXT, segment_id TEXT, enabled INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY, agent TEXT NOT NULL, status TEXT NOT NULL,
  parent_run TEXT, halt_reason TEXT, detector TEXT,
  cost_micros INTEGER NOT NULL DEFAULT 0, steps INTEGER NOT NULL DEFAULT 0,
  started_at REAL NOT NULL DEFAULT 0, ended_at REAL,
  task TEXT, corpus_profile TEXT
);
"""


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


class Store:
    def __init__(self, path: str = "tokenops.db") -> None:
        self.path = path
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.executescript(_SCHEMA)
        self._db.commit()

    def close(self) -> None:
        self._db.close()

    # ---- segments --------------------------------------------------------- #

    def upsert_segment(self, seg: Segment) -> Segment:
        self._db.execute(
            "REPLACE INTO segments(id, name, dimension, tag_key, match_value) VALUES (?,?,?,?,?)",
            (seg.id, seg.name, seg.dimension, seg.tag_key, seg.match_value),
        )
        self._db.commit()
        return seg

    def get_segment(self, sid: str) -> Segment | None:
        row = self._db.execute("SELECT * FROM segments WHERE id=?", (sid,)).fetchone()
        return _segment(row) if row else None

    def list_segments(self) -> list[Segment]:
        return [_segment(r) for r in self._db.execute("SELECT * FROM segments ORDER BY name")]

    def delete_segment(self, sid: str) -> None:
        self._db.execute("DELETE FROM segments WHERE id=?", (sid,))
        self._db.commit()

    # ---- budgets ---------------------------------------------------------- #

    def upsert_budget(self, b: BudgetSpec) -> BudgetSpec:
        self._db.execute(
            "REPLACE INTO budgets(id, limit_micros, dimension, tag_key, period) VALUES (?,?,?,?,?)",
            (b.id, b.limit_micros, b.dimension, b.tag_key, b.period),
        )
        self._db.commit()
        return b

    def get_budget(self, bid: str) -> BudgetSpec | None:
        row = self._db.execute("SELECT * FROM budgets WHERE id=?", (bid,)).fetchone()
        return _budget(row) if row else None

    def list_budgets(self) -> list[BudgetSpec]:
        return [_budget(r) for r in self._db.execute("SELECT * FROM budgets ORDER BY id")]

    def delete_budget(self, bid: str) -> None:
        self._db.execute("DELETE FROM budgets WHERE id=?", (bid,))
        self._db.commit()

    # ---- policy instances ------------------------------------------------- #

    def upsert_policy_instance(self, pi: PolicyInstance) -> PolicyInstance:
        if pi.template not in _TEMPLATES:  # fail closed — same rule as build_governor
            raise ValueError(f"unknown policy template {pi.template!r}; known: {sorted(_TEMPLATES)}")
        self._db.execute(
            "REPLACE INTO policy_instances(id, template, params, agent, budget_id, segment_id, enabled) "
            "VALUES (?,?,?,?,?,?,?)",
            (pi.id, pi.template, json.dumps(pi.params), pi.agent, pi.budget_id, pi.segment_id,
             1 if pi.enabled else 0),
        )
        self._db.commit()
        return pi

    def get_policy_instance(self, pid: str) -> PolicyInstance | None:
        row = self._db.execute("SELECT * FROM policy_instances WHERE id=?", (pid,)).fetchone()
        return _policy(row) if row else None

    def list_policy_instances(self) -> list[PolicyInstance]:
        return [_policy(r) for r in self._db.execute("SELECT * FROM policy_instances ORDER BY template")]

    def delete_policy_instance(self, pid: str) -> None:
        self._db.execute("DELETE FROM policy_instances WHERE id=?", (pid,))
        self._db.commit()

    # ---- the bridge to build_governor ------------------------------------- #

    def governance_config_for(self, agent: str) -> dict:
        """Assemble the exact dict ``build_governor`` consumes for one agent.

        Includes every enabled policy instance scoped to this agent (or to all agents),
        the budgets they reference, and resolves an attached segment into dimension/tag_key
        for segment-scoped templates. One instance per template (last wins) — matches the
        Governor's name-routed registration.
        """
        instances = [pi for pi in self.list_policy_instances()
                     if pi.enabled and (pi.agent is None or pi.agent == agent)]
        budget_ids = {pi.budget_id for pi in instances if pi.budget_id}
        budgets = [_budget_dict(self.get_budget(bid)) for bid in budget_ids if self.get_budget(bid)]

        policies: dict[str, dict] = {}
        for pi in instances:
            params = dict(pi.params)
            if pi.budget_id:
                params["budget"] = pi.budget_id
            if pi.segment_id:
                seg = self.get_segment(pi.segment_id)
                if seg:
                    params.setdefault("dimension", seg.dimension)
                    if seg.tag_key:
                        params.setdefault("tag_key", seg.tag_key)
            policies[pi.template] = params
        return {"governance": {"budgets": budgets, "policies": policies}}

    # ---- runs (dashboard) ------------------------------------------------- #

    def create_run(self, rec: RunRecord) -> RunRecord:
        if not rec.started_at:
            rec.started_at = time.time()
        self._db.execute(
            "REPLACE INTO runs(run_id, agent, status, parent_run, halt_reason, detector, "
            "cost_micros, steps, started_at, ended_at, task, corpus_profile) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (rec.run_id, rec.agent, rec.status, rec.parent_run, rec.halt_reason, rec.detector,
             rec.cost_micros, rec.steps, rec.started_at, rec.ended_at, rec.task, rec.corpus_profile),
        )
        self._db.commit()
        return rec

    def update_run(self, run_id: str, **fields) -> None:
        if not fields:
            return
        cols = ", ".join(f"{k}=?" for k in fields)
        self._db.execute(f"UPDATE runs SET {cols} WHERE run_id=?", (*fields.values(), run_id))
        self._db.commit()

    def get_run(self, run_id: str) -> RunRecord | None:
        row = self._db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        return _run(row) if row else None

    def list_runs(self, *, problematic_only: bool = False, limit: int = 200) -> list[RunRecord]:
        sql = "SELECT * FROM runs"
        if problematic_only:
            sql += " WHERE status IN ('halted','throttled','error')"
        sql += " ORDER BY started_at DESC LIMIT ?"
        return [_run(r) for r in self._db.execute(sql, (limit,))]


# ---- row -> model ---------------------------------------------------------- #

def _segment(r: sqlite3.Row) -> Segment:
    return Segment(id=r["id"], name=r["name"], dimension=r["dimension"],
                   tag_key=r["tag_key"], match_value=r["match_value"])


def _budget(r: sqlite3.Row) -> BudgetSpec:
    return BudgetSpec(id=r["id"], limit_micros=r["limit_micros"], dimension=r["dimension"],
                      tag_key=r["tag_key"], period=r["period"])


def _budget_dict(b: BudgetSpec) -> dict:
    d = {"id": b.id, "limit_micros": b.limit_micros, "dimension": b.dimension, "period": b.period}
    if b.tag_key:
        d["tag_key"] = b.tag_key
    return d


def _policy(r: sqlite3.Row) -> PolicyInstance:
    return PolicyInstance(id=r["id"], template=r["template"], params=json.loads(r["params"]),
                          agent=r["agent"], budget_id=r["budget_id"], segment_id=r["segment_id"],
                          enabled=bool(r["enabled"]))


def _run(r: sqlite3.Row) -> RunRecord:
    return RunRecord(run_id=r["run_id"], agent=r["agent"], status=r["status"],
                     parent_run=r["parent_run"], halt_reason=r["halt_reason"], detector=r["detector"],
                     cost_micros=r["cost_micros"], steps=r["steps"], started_at=r["started_at"],
                     ended_at=r["ended_at"], task=r["task"], corpus_profile=r["corpus_profile"])

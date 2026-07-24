"""SQLite store — the shared backbone for admin config + run history.

One ``tokenops.db`` is shared by the control plane, product UI (Admin/Dashboard), and any
agents that use the same ``TOKENOPS_DB`` (or talk to the plane over HTTP). They agree on
policies, runs, and **ledger accumulators** (spend, inflight, halt). SQLite (WAL) gives
ACID + concurrent readers as a single inspectable, deletable file — no daemon.

The key method is :meth:`Store.governance_config_for`, which assembles exactly the dict
``control.config.build_governor`` already consumes — so the store drops in for static YAML
and ``build_governor`` is unchanged.

Concurrency
-----------
One :class:`Store` instance is safe for concurrent threads in a single process: all DB
access is serialized on an internal :class:`~threading.RLock` (sqlite3 connections are not
re-entrant across threads without that). Multi-statement ledger ops (add-spent, admit,
halt) hold the lock for the whole critical section so counters and halt flags are not torn.

Multi-process: each process opens its own ``Store`` / connection on the same file; WAL +
atomic SQL keep ledger accumulators correct across processes. See ``docs/concurrency.md``.
"""

from __future__ import annotations

import functools
import json
import os
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any, TypeVar

from tokenops.control.models import (
    BudgetSpec,
    PolicyInstance,
    RunAlreadyRegisteredError,
    RunNotRegisteredError,
    RunRecord,
    RunRegistration,
    Segment,
    parse_governance_mode,
)

_F = TypeVar("_F", bound=Callable[..., Any])


def _locked(fn: _F) -> _F:
    """Serialize access to ``self._db``; re-entrant for nested Store method calls."""

    @functools.wraps(fn)
    def wrapper(self: Store, *args: Any, **kwargs: Any) -> Any:
        with self._lock:
            return fn(self, *args, **kwargs)

    return wrapper  # type: ignore[return-value]


def _known_policy_templates() -> frozenset[str]:
    from tokenops.control.config import _TEMPLATES

    return frozenset({*_TEMPLATES, "trajectory_hint"})


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
  task TEXT, dims TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS run_registrations (
  run_id TEXT PRIMARY KEY,
  intent TEXT NOT NULL DEFAULT '',
  user_dims TEXT NOT NULL DEFAULT '{}',
  registered_at REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS ledger_spent (
  budget_id TEXT NOT NULL,
  segment_key TEXT NOT NULL,
  period TEXT NOT NULL DEFAULT 'lifetime',
  spent_micros INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (budget_id, segment_key, period)
);
CREATE TABLE IF NOT EXISTS ledger_inflight (
  segment_key TEXT PRIMARY KEY,
  count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS ledger_halt (
  run_id TEXT PRIMARY KEY,
  halted INTEGER NOT NULL DEFAULT 0,
  halt_reason TEXT
);
CREATE TABLE IF NOT EXISTS trajectory_index (
  id TEXT PRIMARY KEY,
  scope_key TEXT NOT NULL,
  input_hash TEXT NOT NULL,
  input_simhash INTEGER NOT NULL,
  input_preview TEXT NOT NULL,
  source_run_id TEXT NOT NULL,
  step_summary TEXT NOT NULL,
  tool_sequence TEXT NOT NULL,
  cost_micros INTEGER NOT NULL,
  step_count INTEGER NOT NULL,
  quality_score REAL,
  indexed_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_traj_scope_hash ON trajectory_index(scope_key, input_hash);
CREATE INDEX IF NOT EXISTS idx_traj_scope_time ON trajectory_index(scope_key, indexed_at DESC);
CREATE TABLE IF NOT EXISTS trajectory_build_queue (
  run_id TEXT PRIMARY KEY,
  scope_key TEXT NOT NULL,
  input_hash TEXT NOT NULL,
  input_simhash INTEGER NOT NULL,
  input_preview TEXT NOT NULL,
  task_text TEXT NOT NULL,
  cost_micros INTEGER NOT NULL,
  step_count INTEGER NOT NULL,
  enqueued_at REAL NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS run_trajectory_snapshots (
  run_id TEXT PRIMARY KEY,
  window_json TEXT NOT NULL,
  saved_at REAL NOT NULL
);
"""


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


class Store:
    def __init__(self, path: str = "tokenops.db", *, auto_seed: bool = True) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA foreign_keys=ON")
        # Wait up to 5s on lock contention instead of failing immediately (SQLITE_BUSY).
        self._db.execute("PRAGMA busy_timeout=5000")
        self._db.executescript(_SCHEMA)
        self._migrate()
        self._db.commit()
        if auto_seed:
            self.seed_default_governance_if_empty()

    def _migrate(self) -> None:
        # Additive migrations for pre-existing databases.
        cols = {row[1] for row in self._db.execute("PRAGMA table_info(runs)")}
        if "dims" not in cols:
            self._db.execute("ALTER TABLE runs ADD COLUMN dims TEXT NOT NULL DEFAULT '{}'")
        if "parent_span" not in cols:
            self._db.execute("ALTER TABLE runs ADD COLUMN parent_span TEXT")
        reg_cols = {row[1] for row in self._db.execute("PRAGMA table_info(run_registrations)")}
        if "mode" not in reg_cols:
            self._db.execute(
                "ALTER TABLE run_registrations ADD COLUMN mode TEXT NOT NULL DEFAULT 'enforce'"
            )
        if "governance_events" not in cols:
            try:
                self._db.execute(
                    "ALTER TABLE runs ADD COLUMN governance_events TEXT NOT NULL DEFAULT '[]'"
                )
            except sqlite3.OperationalError as exc:
                if "duplicate column" not in str(exc).lower():
                    raise

    @_locked
    def close(self) -> None:
        self._db.close()

    # ---- segments --------------------------------------------------------- #

    def _invalidate_governance_config_cache(self) -> None:
        from tokenops.control.governance_cache import clear_governance_config_cache

        clear_governance_config_cache(store_path=self.path)

    @_locked
    def upsert_segment(self, seg: Segment) -> Segment:
        self._db.execute(
            "REPLACE INTO segments(id, name, dimension, tag_key, match_value) VALUES (?,?,?,?,?)",
            (seg.id, seg.name, seg.dimension, seg.tag_key, seg.match_value),
        )
        self._db.commit()
        self._invalidate_governance_config_cache()
        return seg

    @_locked
    def get_segment(self, sid: str) -> Segment | None:
        row = self._db.execute("SELECT * FROM segments WHERE id=?", (sid,)).fetchone()
        return _segment(row) if row else None

    @_locked
    def list_segments(self) -> list[Segment]:
        return [_segment(r) for r in self._db.execute("SELECT * FROM segments ORDER BY name")]

    @_locked
    def delete_segment(self, sid: str) -> None:
        self._db.execute("DELETE FROM segments WHERE id=?", (sid,))
        self._db.commit()
        self._invalidate_governance_config_cache()

    # ---- budgets ---------------------------------------------------------- #

    @_locked
    def upsert_budget(self, b: BudgetSpec) -> BudgetSpec:
        self._db.execute(
            "REPLACE INTO budgets(id, limit_micros, dimension, tag_key, period) VALUES (?,?,?,?,?)",
            (b.id, b.limit_micros, b.dimension, b.tag_key, b.period),
        )
        self._db.commit()
        self._invalidate_governance_config_cache()
        return b

    @_locked
    def get_budget(self, bid: str) -> BudgetSpec | None:
        row = self._db.execute("SELECT * FROM budgets WHERE id=?", (bid,)).fetchone()
        return _budget(row) if row else None

    @_locked
    def list_budgets(self) -> list[BudgetSpec]:
        return [_budget(r) for r in self._db.execute("SELECT * FROM budgets ORDER BY id")]

    @_locked
    def delete_budget(self, bid: str) -> None:
        self._db.execute("DELETE FROM budgets WHERE id=?", (bid,))
        self._db.commit()
        self._invalidate_governance_config_cache()

    # ---- policy instances ------------------------------------------------- #

    @_locked
    def upsert_policy_instance(self, pi: PolicyInstance) -> PolicyInstance:
        if (
            pi.template not in _known_policy_templates()
        ):  # fail closed — same rule as build_governor
            raise ValueError(
                f"unknown policy template {pi.template!r}; known: {sorted(_known_policy_templates())}"
            )
        self._db.execute(
            "REPLACE INTO policy_instances(id, template, params, agent, budget_id, segment_id, enabled) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                pi.id,
                pi.template,
                json.dumps(pi.params),
                pi.agent,
                pi.budget_id,
                pi.segment_id,
                1 if pi.enabled else 0,
            ),
        )
        self._db.commit()
        self._invalidate_governance_config_cache()
        return pi

    @_locked
    def get_policy_instance(self, pid: str) -> PolicyInstance | None:
        row = self._db.execute("SELECT * FROM policy_instances WHERE id=?", (pid,)).fetchone()
        return _policy(row) if row else None

    @_locked
    def list_policy_instances(self) -> list[PolicyInstance]:
        return [
            _policy(r) for r in self._db.execute("SELECT * FROM policy_instances ORDER BY template")
        ]

    @_locked
    def delete_policy_instance(self, pid: str) -> None:
        self._db.execute("DELETE FROM policy_instances WHERE id=?", (pid,))
        self._db.commit()
        self._invalidate_governance_config_cache()

    @_locked
    def seed_default_governance_if_empty(self, governance: dict | None = None) -> bool:
        """Load budgets + policies from config YAML when the store has none yet.

        Skipped when ``TOKENOPS_SKIP_GOVERNANCE_SEED=1`` or policy instances already
        exist (Admin edits are never overwritten).
        """
        if os.environ.get("TOKENOPS_SKIP_GOVERNANCE_SEED"):
            return False
        if self.list_policy_instances():
            return False
        return self._apply_governance_yaml(governance)

    @_locked
    def clear_all(self) -> None:
        """Delete every row (runs, registrations, governance, ledger). Schema is preserved."""
        for table in (
            "runs",
            "run_registrations",
            "policy_instances",
            "budgets",
            "segments",
            "ledger_spent",
            "ledger_inflight",
            "ledger_halt",
        ):
            self._db.execute(f"DELETE FROM {table}")
        self._db.commit()
        self._invalidate_governance_config_cache()

    @_locked
    def clear_governance(self) -> None:
        """Delete segments, budgets, and policy instances only."""
        for table in ("policy_instances", "budgets", "segments"):
            self._db.execute(f"DELETE FROM {table}")
        self._db.commit()
        self._invalidate_governance_config_cache()

    @_locked
    def reseed_governance(self, governance: dict | None = None) -> bool:
        """Replace governance config from YAML (discards Admin edits)."""
        self.clear_governance()
        return self._apply_governance_yaml(governance)

    @_locked
    def _apply_governance_yaml(self, governance: dict | None = None) -> bool:
        if governance is None:
            from tokenops.config.loader import load_governance_yaml

            governance = load_governance_yaml()
        if not governance:
            return False

        for spec in governance.get("budgets") or []:
            self.upsert_budget(
                BudgetSpec(
                    id=spec["id"],
                    limit_micros=spec.get("limit_micros"),
                    dimension=spec.get("dimension", "run"),
                    tag_key=spec.get("tag_key"),
                    period=spec.get("period", "lifetime"),
                )
            )

        for template, raw_params in (governance.get("policies") or {}).items():
            params = dict(raw_params or {})
            budget_id = params.pop("budget", None)
            self.upsert_policy_instance(
                PolicyInstance(
                    id=f"seed_{template}",
                    template=template,
                    params=params,
                    budget_id=budget_id,
                )
            )
        return True

    # ---- run registration (attribution) ----------------------------------- #

    @_locked
    def register_run(self, reg: RunRegistration) -> RunRegistration:
        if self.get_run_registration(reg.run_id) is not None:
            raise RunAlreadyRegisteredError(f"run {reg.run_id!r} is already registered")
        self._db.execute(
            "INSERT INTO run_registrations(run_id, intent, user_dims, mode, registered_at) VALUES (?,?,?,?,?)",
            (reg.run_id, reg.intent, json.dumps(reg.user_dims), reg.mode.value, time.time()),
        )
        self._db.commit()
        return reg

    @_locked
    def resolve_run(self, run_id: str) -> RunRegistration:
        reg = self.get_run_registration(run_id)
        if reg is None:
            raise RunNotRegisteredError(f"run {run_id!r} is not registered")
        return reg

    @_locked
    def get_run_registration(self, run_id: str) -> RunRegistration | None:
        row = self._db.execute(
            "SELECT * FROM run_registrations WHERE run_id=?", (run_id,)
        ).fetchone()
        return _registration(row) if row else None

    # ---- the bridge to build_governor ------------------------------------- #

    def governance_config_for(self, agent: str) -> dict:
        """Assemble the exact dict ``build_governor`` consumes for one agent.

        Includes every enabled policy instance scoped to this agent (or to all agents),
        the budgets they reference, and resolves an attached segment into dimension/tag_key
        for segment-scoped templates. One instance per template (last wins) — matches the
        Governor's name-routed registration.

        Results are cached in-process (§10); invalidated on governance writes or via
        :func:`~tokenops.control.governance_cache.clear_governance_config_cache`.
        """
        from tokenops.control.governance_cache import get_cached_governance_config

        return get_cached_governance_config(
            self.path,
            agent,
            lambda: self._assemble_governance_config(agent),
        )

    @_locked
    def _assemble_governance_config(self, agent: str) -> dict:
        instances = [
            pi
            for pi in self.list_policy_instances()
            if pi.enabled and (pi.agent is None or pi.agent == agent)
        ]
        budget_ids = {pi.budget_id for pi in instances if pi.budget_id}
        budgets = []
        for bid in budget_ids:
            budget = self.get_budget(bid)
            if budget is not None:
                budgets.append(_budget_dict(budget))

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

    @_locked
    def create_run(self, rec: RunRecord) -> RunRecord:
        if not rec.started_at:
            rec.started_at = time.time()
        self._db.execute(
            "REPLACE INTO runs(run_id, agent, status, parent_run, parent_span, halt_reason, detector, "
            "cost_micros, steps, started_at, ended_at, task, dims) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                rec.run_id,
                rec.agent,
                rec.status,
                rec.parent_run,
                rec.parent_span,
                rec.halt_reason,
                rec.detector,
                rec.cost_micros,
                rec.steps,
                rec.started_at,
                rec.ended_at,
                rec.task,
                json.dumps(rec.dims),
            ),
        )
        self._db.commit()
        return rec

    @_locked
    def update_run(self, run_id: str, **fields) -> None:
        if not fields:
            return
        if "governance_events" in fields and not isinstance(fields["governance_events"], str):
            fields["governance_events"] = json.dumps(fields["governance_events"])
        cols = ", ".join(f"{k}=?" for k in fields)
        self._db.execute(f"UPDATE runs SET {cols} WHERE run_id=?", (*fields.values(), run_id))
        self._db.commit()

    @_locked
    def get_run(self, run_id: str) -> RunRecord | None:
        row = self._db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        return _run(row) if row else None

    @_locked
    def list_runs(self, *, problematic_only: bool = False, limit: int = 200) -> list[RunRecord]:
        sql = "SELECT * FROM runs"
        if problematic_only:
            sql += " WHERE status IN ('halted','throttled','error')"
        sql += " ORDER BY started_at DESC LIMIT ?"
        return [_run(r) for r in self._db.execute(sql, (limit,))]

    @_locked
    def run_tag_keys(self, *, limit: int = 500) -> list[str]:
        """Distinct segment-tag keys seen across recent runs — the choices a dashboard can
        group runs by (in addition to ``agent``)."""
        keys: set[str] = set()
        for r in self.list_runs(limit=limit):
            keys.update(r.dims.keys())
        return sorted(keys)

    # ---- shared ledger (cross-process spend / inflight / halt) ------------ #

    @_locked
    def ledger_add_spent(
        self,
        budget_id: str,
        segment_key: str,
        period: str,
        delta: int,
    ) -> int:
        """Atomically increment a budget accumulator; return the new total."""
        self._db.execute(
            "INSERT INTO ledger_spent(budget_id, segment_key, period, spent_micros) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(budget_id, segment_key, period) "
            "DO UPDATE SET spent_micros = spent_micros + excluded.spent_micros",
            (budget_id, segment_key, period, delta),
        )
        row = self._db.execute(
            "SELECT spent_micros FROM ledger_spent "
            "WHERE budget_id=? AND segment_key=? AND period=?",
            (budget_id, segment_key, period),
        ).fetchone()
        self._db.commit()
        return int(row[0]) if row else 0

    @_locked
    def ledger_get_spent(self, budget_id: str, segment_key: str, period: str) -> int:
        row = self._db.execute(
            "SELECT spent_micros FROM ledger_spent "
            "WHERE budget_id=? AND segment_key=? AND period=?",
            (budget_id, segment_key, period),
        ).fetchone()
        return int(row[0]) if row else 0

    @_locked
    def ledger_admit(self, segment_key: str) -> int:
        self._db.execute(
            "INSERT INTO ledger_inflight(segment_key, count) VALUES (?, 1) "
            "ON CONFLICT(segment_key) DO UPDATE SET count = count + 1",
            (segment_key,),
        )
        row = self._db.execute(
            "SELECT count FROM ledger_inflight WHERE segment_key=?",
            (segment_key,),
        ).fetchone()
        self._db.commit()
        return int(row[0]) if row else 0

    @_locked
    def ledger_complete(self, segment_key: str) -> int:
        self._db.execute(
            "UPDATE ledger_inflight SET count = MAX(0, count - 1) WHERE segment_key=?",
            (segment_key,),
        )
        row = self._db.execute(
            "SELECT count FROM ledger_inflight WHERE segment_key=?",
            (segment_key,),
        ).fetchone()
        self._db.commit()
        return int(row[0]) if row else 0

    @_locked
    def ledger_inflight(self, segment_key: str) -> int:
        row = self._db.execute(
            "SELECT count FROM ledger_inflight WHERE segment_key=?",
            (segment_key,),
        ).fetchone()
        return int(row[0]) if row else 0

    @_locked
    def ledger_mark_halted(self, run_id: str, reason: str = "") -> None:
        self._db.execute(
            "INSERT INTO ledger_halt(run_id, halted, halt_reason) VALUES (?, 1, ?) "
            "ON CONFLICT(run_id) DO UPDATE SET halted=1, "
            "halt_reason=COALESCE(excluded.halt_reason, ledger_halt.halt_reason)",
            (run_id, reason or None),
        )
        self._db.commit()

    @_locked
    def ledger_is_halted(self, run_id: str) -> bool:
        row = self._db.execute(
            "SELECT halted FROM ledger_halt WHERE run_id=?",
            (run_id,),
        ).fetchone()
        return bool(row and row[0])

    @_locked
    def ledger_halt_reason(self, run_id: str) -> str | None:
        row = self._db.execute(
            "SELECT halt_reason FROM ledger_halt WHERE run_id=?",
            (run_id,),
        ).fetchone()
        return row[0] if row else None

    @_locked
    def ledger_clear_halt(self, run_id: str) -> None:
        self._db.execute(
            "INSERT INTO ledger_halt(run_id, halted, halt_reason) VALUES (?, 0, NULL) "
            "ON CONFLICT(run_id) DO UPDATE SET halted=0, halt_reason=NULL",
            (run_id,),
        )
        self._db.commit()

    # ---- trajectory hint index -------------------------------------------- #

    @_locked
    def save_trajectory_snapshot(self, run_id: str, window_json: str) -> None:
        self._db.execute(
            "REPLACE INTO run_trajectory_snapshots(run_id, window_json, saved_at) VALUES (?,?,?)",
            (run_id, window_json, time.time()),
        )
        self._db.commit()

    @_locked
    def enqueue_trajectory_build(
        self,
        *,
        run_id: str,
        scope_key: str,
        input_hash: str,
        input_simhash: int,
        input_preview: str,
        task_text: str,
        cost_micros: int,
        step_count: int,
    ) -> None:
        self._db.execute(
            "REPLACE INTO trajectory_build_queue("
            "run_id, scope_key, input_hash, input_simhash, input_preview, task_text, "
            "cost_micros, step_count, enqueued_at, attempts"
            ") VALUES (?,?,?,?,?,?,?,?,?,0)",
            (
                run_id,
                scope_key,
                input_hash,
                input_simhash,
                input_preview,
                task_text,
                cost_micros,
                step_count,
                time.time(),
            ),
        )
        self._db.commit()

    @_locked
    def drain_trajectory_build_queue(
        self,
        *,
        limit: int = 8,
        max_age_days: int = 30,
        max_entries_per_scope: int = 500,
    ) -> int:
        from tokenops.control.trajectory.compress import compress_trajectory
        from tokenops.control.trajectory.serialize import window_from_json

        rows = self._db.execute(
            "SELECT * FROM trajectory_build_queue ORDER BY enqueued_at ASC LIMIT ?",
            (limit,),
        ).fetchall()
        done = 0
        for row in rows:
            run_id = row["run_id"]
            try:
                snap = self._db.execute(
                    "SELECT window_json FROM run_trajectory_snapshots WHERE run_id=?",
                    (run_id,),
                ).fetchone()
                if not snap:
                    self._db.execute("DELETE FROM trajectory_build_queue WHERE run_id=?", (run_id,))
                    self._db.commit()
                    continue
                steps = window_from_json(snap["window_json"])
                step_summary, tool_sequence = compress_trajectory(steps)
                self._insert_trajectory_index(
                    scope_key=row["scope_key"],
                    input_hash=row["input_hash"],
                    input_simhash=int(row["input_simhash"]),
                    input_preview=row["input_preview"],
                    source_run_id=run_id,
                    step_summary=step_summary,
                    tool_sequence=tool_sequence,
                    cost_micros=int(row["cost_micros"]),
                    step_count=int(row["step_count"]),
                    max_age_days=max_age_days,
                    max_entries_per_scope=max_entries_per_scope,
                )
                self._db.execute("DELETE FROM trajectory_build_queue WHERE run_id=?", (run_id,))
                self._db.commit()
                done += 1
            except Exception:
                self._db.execute(
                    "UPDATE trajectory_build_queue SET attempts = attempts + 1 WHERE run_id=?",
                    (run_id,),
                )
                self._db.commit()
        return done

    @_locked
    def _insert_trajectory_index(
        self,
        *,
        scope_key: str,
        input_hash: str,
        input_simhash: int,
        input_preview: str,
        source_run_id: str,
        step_summary: str,
        tool_sequence: str,
        cost_micros: int,
        step_count: int,
        quality_score: float | None = None,
        max_age_days: int = 30,
        max_entries_per_scope: int = 500,
    ) -> None:
        indexed_at = time.time()
        row_id = new_id("traj")
        self._db.execute(
            "INSERT INTO trajectory_index("
            "id, scope_key, input_hash, input_simhash, input_preview, source_run_id, "
            "step_summary, tool_sequence, cost_micros, step_count, quality_score, indexed_at"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                row_id,
                scope_key,
                input_hash,
                input_simhash,
                input_preview,
                source_run_id,
                step_summary,
                tool_sequence,
                cost_micros,
                step_count,
                quality_score,
                indexed_at,
            ),
        )
        self._prune_trajectory_scope(
            scope_key, max_age_days=max_age_days, max_entries=max_entries_per_scope
        )
        self._db.commit()

    @_locked
    def _prune_trajectory_scope(
        self,
        scope_key: str,
        *,
        max_age_days: int,
        max_entries: int,
    ) -> None:
        cutoff = time.time() - max_age_days * 86400
        self._db.execute(
            "DELETE FROM trajectory_index WHERE scope_key=? AND indexed_at < ?",
            (scope_key, cutoff),
        )
        count = self._db.execute(
            "SELECT COUNT(*) FROM trajectory_index WHERE scope_key=?",
            (scope_key,),
        ).fetchone()[0]
        overflow = int(count) - max_entries
        if overflow > 0:
            self._db.execute(
                "DELETE FROM trajectory_index WHERE id IN ("
                "  SELECT id FROM trajectory_index WHERE scope_key=?"
                "  ORDER BY COALESCE(quality_score, 0) ASC, cost_micros DESC, indexed_at ASC"
                "  LIMIT ?"
                ")",
                (scope_key, overflow),
            )

    @_locked
    def lookup_trajectory_index(
        self,
        *,
        scope_key: str,
        input_hash: str,
        input_simhash: int,
        max_age_days: int,
        simhash_threshold: int,
    ) -> dict[str, Any] | None:
        from tokenops.control.policies._util import hamming
        from tokenops.control.trajectory.scope import simhash_from_sqlite

        cutoff = time.time() - max_age_days * 86400
        query_fp = simhash_from_sqlite(input_simhash)
        exact = self._db.execute(
            "SELECT * FROM trajectory_index "
            "WHERE scope_key=? AND input_hash=? AND indexed_at >= ? "
            "ORDER BY COALESCE(quality_score, 0) DESC, cost_micros ASC, indexed_at DESC "
            "LIMIT 1",
            (scope_key, input_hash, cutoff),
        ).fetchone()
        if exact:
            return self._trajectory_hit_row(exact, match="exact")

        candidates = self._db.execute(
            "SELECT * FROM trajectory_index WHERE scope_key=? AND indexed_at >= ? "
            "ORDER BY indexed_at DESC LIMIT 500",
            (scope_key, cutoff),
        ).fetchall()
        best = None
        best_dist = simhash_threshold + 1
        for row in candidates:
            dist = hamming(query_fp, simhash_from_sqlite(int(row["input_simhash"])))
            if dist <= simhash_threshold and dist < best_dist:
                best = row
                best_dist = dist
        if best is None:
            return None
        return self._trajectory_hit_row(best, match="simhash")

    @staticmethod
    def _trajectory_hit_row(row: sqlite3.Row, *, match: str) -> dict[str, Any]:
        return {
            "source_run_id": row["source_run_id"],
            "step_count": int(row["step_count"]),
            "cost_micros": int(row["cost_micros"]),
            "tool_sequence": row["tool_sequence"],
            "step_summary": row["step_summary"],
            "match": match,
        }

    @_locked
    def get_trajectory_index_by_run(self, source_run_id: str) -> dict[str, Any] | None:
        row = self._db.execute(
            "SELECT * FROM trajectory_index WHERE source_run_id=? ORDER BY indexed_at DESC LIMIT 1",
            (source_run_id,),
        ).fetchone()
        return dict(row) if row else None


# ---- row -> model ---------------------------------------------------------- #


def _registration(r: sqlite3.Row) -> RunRegistration:
    return RunRegistration(
        run_id=r["run_id"],
        intent=r["intent"] or "",
        user_dims=json.loads(r["user_dims"] or "{}"),
        mode=parse_governance_mode(r["mode"] if "mode" in r.keys() else None),
    )


def _segment(r: sqlite3.Row) -> Segment:
    return Segment(
        id=r["id"],
        name=r["name"],
        dimension=r["dimension"],
        tag_key=r["tag_key"],
        match_value=r["match_value"],
    )


def _budget(r: sqlite3.Row) -> BudgetSpec:
    return BudgetSpec(
        id=r["id"],
        limit_micros=r["limit_micros"],
        dimension=r["dimension"],
        tag_key=r["tag_key"],
        period=r["period"],
    )


def _budget_dict(b: BudgetSpec) -> dict:
    d = {"id": b.id, "limit_micros": b.limit_micros, "dimension": b.dimension, "period": b.period}
    if b.tag_key:
        d["tag_key"] = b.tag_key
    return d


def _policy(r: sqlite3.Row) -> PolicyInstance:
    return PolicyInstance(
        id=r["id"],
        template=r["template"],
        params=json.loads(r["params"]),
        agent=r["agent"],
        budget_id=r["budget_id"],
        segment_id=r["segment_id"],
        enabled=bool(r["enabled"]),
    )


def _run(r: sqlite3.Row) -> RunRecord:
    dims = json.loads((r["dims"] if "dims" in r.keys() else None) or "{}")
    keys = r.keys()
    gov_raw = r["governance_events"] if "governance_events" in keys else "[]"
    try:
        governance_events = json.loads(gov_raw or "[]")
    except json.JSONDecodeError:
        governance_events = []
    return RunRecord(
        run_id=r["run_id"],
        agent=r["agent"],
        status=r["status"],
        parent_run=r["parent_run"],
        parent_span=r["parent_span"] if "parent_span" in keys else None,
        halt_reason=r["halt_reason"],
        detector=r["detector"],
        cost_micros=r["cost_micros"],
        steps=r["steps"],
        started_at=r["started_at"],
        ended_at=r["ended_at"],
        task=r["task"],
        dims=dims,
        governance_events=governance_events,
    )

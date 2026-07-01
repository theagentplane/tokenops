# TokenOps Control Plane — status

Governance for the two-agent A2A test bench: **register → measure → record → detect → decide → act**.
The agent (data plane) stays vanilla; the control plane taps boundary crossings and enforces on
**cost** (micro-USD integers). **108 tests pass** (1 skipped, 1 warning — Starlette/httpx deprecation).

## What it does (jobs → status)

| Job | Status | Where |
|---|---|---|
| Run registration (`intent`, `user_dims`) | ✅ | `POST /v1/runs`, `control/store.py` `run_registrations` |
| Attribution + span propagation | ✅ | `control/attribution.py`, `control/context.py`, A2A headers |
| Chronicle `@boundary` record/replay | ✅ | `chronicle/boundary.py`, `chronicle/session.py` |
| Govern ingest from boundaries | ✅ | `control/boundary.py` → `Governor.observe` |
| Provider wrap (pre_call) | ✅ | `control/integration.py` `wrap_complete` |
| Ledger (spend, inflight, steps, window) | ✅ | `control/ledger.py` + `control/pricing.py` |
| Cross-process ledger (spend + halt in SQLite) | ✅ | `control/store.py` `ledger_*` tables; `build_governor(..., store=store)` |
| 10 policy templates + Governor harness | ✅ | `control/policies/*`, `control/engine.py` |
| Actuators (HALT · MUTATE · INJECT · REJECT/QUEUE) | ✅ | `ApplyControls`, `wrap_complete` |
| Native server enforcement | ✅ | `agents/*/native/server.py` (LangChain: #6) |
| SQLite store + auto-seed from YAML | ✅ | `control/store.py`, `config/default.yaml` `governance:` |
| Admin UI (edit budgets/policies) | ✅ | `ui/pages/1_Admin.py` |
| Dashboard (runs, cost, read-only gov preview) | ✅ | `ui/pages/2_Dashboard.py` |
| Run simulator (in-process trace + control plane) | ✅ | `ui/pages/3_Simulator.py`, `ui/simulator.py` |
| DB reset / reseed scripts | ✅ | `scripts/db_clear.py`, `scripts/db_reseed.py`, `make db-reset` |
| User/tag segment-scoped budgets (config) | ⏳ | machinery in `segment_key_for`; seed is run-only ([#8](https://github.com/theagentplane/tokenops/issues/8)) |
| Composite segment matchers (AND) | ⏳ | [#5](https://github.com/theagentplane/tokenops/issues/5) |

## Architecture (one governed run)

```
POST /v1/runs  →  register run_id + intent + user_dims (SQLite)
POST /v1/tasks + X-TokenOps-Run-Id
  → build_governor(store.governance_config_for(agent), store=store)
  → run_scope + governance_scope
  → agent loop:
       complete() ──▶ wrap_complete ──▶ pre_call ──▶ detect→decide→apply
       @boundary  ──▶ chronicle envelope + emit_observation ──▶ observe ──▶ ledger.record
       delegate   ──▶ child agent (same run_id, parent span header) ──▶ rollup observe
  → store.update_run(RunRecord) ──▶ Dashboard
```

Layers: `core` → `ledger` → `policies` → `engine` → `config`/`store` → `integration` /
`boundary` / `attribution` / `chronicle`. See `docs/architecture.md` and `docs/run-attribution.md`.

## Governance config (SQLite)

- **Source of truth:** `tokenops.db` (env `TOKENOPS_DB`), not the agent section of `default.yaml`.
- **Auto-seed:** on first `Store()` open, if no policy instances exist, seed from
  `default.yaml` `governance:` block (1 budget `run_llm_cap` @ $2/run, 10 policies).
- **Admin edits** apply on the next run; no server restart.
- **Reset:** `make db-reset` (clear all + reseed) or `make db-reseed` (governance only).

### Budget vs policy

| Concept | Role |
|---|---|
| **Budget** | Spend bucket + cap (`dimension`: run / user / tag / …). Ledger accumulates micros per segment key. |
| **Policy** | (Detector, fix) pair. Some link to a budget (`cost_budget`, `pre_call_worst_case`, `cost_guard`); others use params only (`step_cap`, `tool_fix`, …). |

Seeded config is **run-scoped only** — registration `user_dims` are stored but do not yet scope policies ([#8](https://github.com/theagentplane/tokenops/issues/8)).

## The 10 policies

`cost_budget` · `pre_call_worst_case` · `step_cap` · `concurrency_cap` · `tool_fix` ·
`tool_output_cap` · `progress_guard` · `cost_guard` · `context_compaction` · `output_runaway`.
Per-policy docs: `docs/policies/`.

## Run it

```bash
make install
make db-reset          # optional: clean DB + seed governance
make run               # research + summarize + Streamlit (auto-frees ports 8001/8002/8501)

python -m pytest -q    # 108 passed
```

Streamlit pages: **Test Bench** (live A2A) · **Run simulator** (in-process, demo mode OK) ·
**Policy admin** (edit budgets/policies) · **Dashboard** (runs + cost).

## Proof loops

- **Offline:** `tests/test_attribution_ledger_policies_e2e.py` — register → govern → HALT on `step_cap`.
- **HTTP:** same file — `POST /v1/runs` → `POST /v1/tasks` with run header.
- **Simulator:** `ui/simulator.py` — live timeline of pre_call / observe / signals / spans.
- **Halt demo:** Admin → set `step_cap` `max_steps: 3` or run `python scripts/prep_ledger_comparison.py` then **Run simulator** (shared-ledger budget demo).
- **Shared ledger:** `tests/test_cross_process_budget_gating.py` · `docs/shared-ledger-comparison.md`

## Deferred

LangChain governance ([#6](https://github.com/theagentplane/tokenops/issues/6)) · composite segment matchers ([#5](https://github.com/theagentplane/tokenops/issues/5)) · streaming CANCEL/RETRY · cross-process step_cap sum.

## Docs

`docs/run-attribution.md` · `docs/architecture.md` · `docs/shared-ledger-comparison.md` · `docs/testing.md` ·
`docs/instrumentation-contract.md` · `docs/governance-policy.md`

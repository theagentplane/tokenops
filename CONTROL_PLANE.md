# TokenOps Control Plane — status

Governance for the two-agent A2A test bench: **measure → record → detect → decide → act**.
The agent (data plane) stays vanilla; the control plane taps two seams and enforces on
**cost** (micro-USD integers). 71 tests pass (1 skipped — needs `fastapi`).

## What it does (jobs → status)

| Job | Status | Where |
|---|---|---|
| Ingest instrumentation events | ✅ | `control/integration.py` `make_on_step` → `Governor.observe` |
| Ledger tracks runtime metrics (spend, inflight, steps, window) | ✅ | `control/ledger.py` (+ `control/pricing.py` tokens→cost) |
| Policy templates + execution harness + ledger hook | ✅ | `control/policies/*` (10), `control/engine.py` `Governor` |
| Actuators at the agent surface | ✅ HALT · MUTATE · INJECT · REJECT/QUEUE  ·  ⛔ CANCEL/RETRY (deferred) | `control/engine.py` `ApplyControls`, `wrap_complete` |
| Enforce decisions on the live agent | ✅ | per-run governor in `agents/*/native/server.py` |
| Admin UI: policy instances + segments | ✅ | `ui/pages/1_Admin.py` + `control/store.py` |
| Dashboard: runs, failures, cost | ✅ | `ui/pages/2_Dashboard.py` |
| Agent emits instrumentation/attribution | — | contract in `docs/instrumentation-contract.md` |

## Architecture (one governed run)

```
agent loop ──complete()──▶ wrap_complete ──▶ Governor.pre_call ─▶ detect→decide→apply
                                              (MUTATE cap/model · REJECT→429 · HALT)
           ──on_step()───▶ make_on_step ──▶ Governor.observe ─▶ ledger.record ─▶ detect→decide→apply
                                              (HALT→partial 200 · INJECT next msg)
config (SQLite store) ─▶ build_governor   |   each run → RunRecord (SQLite) ─▶ Dashboard
```

Layers: `core` (vocabulary) → `ledger` (state) → `policies` (10) → `engine` (Governor +
OUT connectors) → `config`/`store` (declarative + persistence) → `integration` (the two
taps). Dependencies point one way; the agent never imports control internals.
See `docs/architecture.md`.

## The 10 policies

`cost_budget` (HALT, the guarantee) · `pre_call_worst_case` (MUTATE→HALT) · `step_cap` (HALT) ·
`concurrency_cap` (REJECT/QUEUE) · `tool_fix` (INJECT→HALT) · `tool_output_cap` (INJECT) ·
`progress_guard` (INJECT→HALT) · `cost_guard` (INJECT/MUTATE) · `context_compaction` (MUTATE) ·
`output_runaway` (RETRY/INJECT). Per-policy docs: `../tokenops-lld/policies/`.

## Run it

```bash
# tests (no API key, fully offline)
python -m pytest -q                 # 71 passed, 1 skipped

# the governed bench (needs fastapi/streamlit + API keys)
make research-server                # per-run governor reads policies from tokenops.db
make summarize-server
make ui                             # Run pipeline · Admin · Dashboard pages
```

Config & runs persist in one SQLite file (`TOKENOPS_DB`, default `tokenops.db`), shared by
both servers and both UIs. Admin writes policies → servers enforce them → Dashboard shows
halted/throttled runs with reason + cost.

## Proof loop (offline test)

`tests/test_server_enforcement.py`: an Admin-created `step_cap` halts a live research run
(model call faked) → boundary returns a structured partial → a halted `RunRecord` is
persisted → the Dashboard would list it with reason + cost.

## Deferred by design (need streaming or agent-surface changes)

CANCEL (no streaming provider) · RETRY loop (wrap must observe output) · programmatic
prompt compaction & tool-result replacement (need agent hooks). The carry-based INJECT and
output-cap MUTATE cover the common cases today. Details in `docs/instrumentation-contract.md`.

## Docs

`docs/architecture.md` · `docs/testing.md` · `docs/instrumentation-contract.md` ·
`../tokenops-lld/` (LLD, `halt.md`, `controls.md`, per-policy).

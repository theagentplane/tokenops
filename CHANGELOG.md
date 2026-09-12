# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `tokenops.control.ledger_backend` — the `LedgerBackend` protocol and
  `HttpLedgerBackend` for the remote-only rewrite (#118). One interface for every
  control-plane read/write; `apply_events(list[LedgerEvent])` is the only write path
  (a future buffered backend wraps it). Targets `agentplane-control-plane` 0.2.0
  (`precheck` / `events:batch`). Not yet wired into `Ledger` / `ControlPlaneClient`.
- `tests/fakes.py::FakeLedgerBackend` (in-memory) + `tests/test_ledger_backend_contract.py`
  — parametrised over the fake and a real `control_plane.app` (in-process ASGI) so the
  fake can't drift from the plane.
- `[contract]` optional-dependency group (`agentplane-control-plane>=0.2.0`). Kept out
  of `[dev]` while the 0.2.0 line is unreleased; the plane-backed tests
  `importorskip("control_plane")`, so `[dev]`-only CI stays green.
- `Ledger.close_run(run_id)` — drops the per-process `LocalRunState`; called by
  `tokenops_run` on scope exit so a long-lived / shared-governor process does not
  accumulate per-run window state (#115).
- `PolicyInstance.data_scope` (`local` | `global`, default `local`) — which tier a
  policy's detector reads: Tier-1 `LocalRunState` cache, or the plane's authoritative
  state via `precheck` (#118). Persisted (`policy_instances.data_scope`, additive
  migration) and round-tripped through `governance_config_for`; not yet consumed by
  `build_governor` — the Governor doesn't group detectors by scope until the
  `LedgerBackend` rewire lands.
- `Ledger(backend=...)` — routes every write through `LedgerBackend.apply_events` and
  every spend/inflight/halt read through `read_state` (`precheck`), alongside the
  existing `store=`/in-memory modes (mutually exclusive with `store`) (#118).
  `step`/`spent_add` batch together per crossing so the ack's `totals` cover the run
  total in one round trip; `admit`/`complete`/`halt_mark`/`halt_clear` are separate
  one-shot writes. `velocity`/`recent`/`window`/`step_count` stay Tier-1-only (never a
  backend round trip) — those are inherently local, per-process reads. Not yet wired
  into `build_governor`/`ControlPlaneClient`; `tests/test_ledger_backend_mode.py`
  exercises it directly against `FakeLedgerBackend`, including two `Ledger` instances
  sharing one backend (the cross-process case).
- `tokenops.control.dev_plane` — launches a real `agentplane-control-plane` on a real
  localhost TCP port, in-process. Used by `tokenops.demo` (below) and by
  `tests/conftest.py::live_plane_url` for tests that must exercise
  `ControlPlaneClient.from_env()` itself (an in-process ASGI app isn't reachable that
  way — `from_env()` builds its own plain `httpx.Client`).

### Changed

- **tokenops has no ledger of its own anymore (#118) — `ControlPlaneClient.from_env()`
  requires `CONTROL_PLANE_URL`/`TOKENOPS_URL` and raises if neither is set.** There is
  no more `TOKENOPS_EMBEDDED` env var and no code path left that silently falls back to
  a local SQLite ledger; `build_governor`/`tokenops_run` construct `Ledger(backend=...)`
  (an `HttpLedgerBackend`, i.e. real `precheck`/`events:batch` traffic to the plane) for
  every live run. The `store=` constructor kwarg on `ControlPlaneClient`/`tokenops_run`
  remains as an explicit, visible test-only escape hatch (dependency injection for unit
  tests that don't want a running plane) — it is never reachable from `from_env()`, so
  no environment misconfiguration can select it.
- `should_mount_run_registration()` always returns `False` now — registration is
  always centralized on the plane; there's no embedded mode left for an agent to
  self-host `POST /v1/runs` under.
- `tokenops.demo` (`python -m tokenops.demo`) launches a real control plane in-process
  (`tokenops.control.dev_plane`) instead of using the now-removed embedded ledger, and
  configures its budget/policy over the plane's own HTTP API (`PUT /v1/budgets` /
  `PUT /v1/policies`) — the zero-setup promise holds, but needs
  `agentplane-control-plane` importable (`pip install "agent-tokenops[contract]"` today,
  or once released; otherwise point `CONTROL_PLANE_URL` at a plane you're already
  running).
- CI now installs `agentplane-control-plane` straight from the control-plane repo
  (`git+https://github.com/theagentplane/control-plane@main`) in addition to
  `.[dev,contract]` — the `[contract]` tests and the `tests/examples/` e2e suite
  (`tests/conftest.py::live_plane_url`) now actually run a real control plane in CI
  instead of silently skipping; they're load-bearing coverage now, not optional.
- `tests/examples/test_bench_e2e.py` and `tests/examples/test_triad_e2e.py` now
  configure their policies/budgets on a real, in-process control plane
  (`live_plane_url`) over its own HTTP API (`PUT /v1/budgets` / `PUT /v1/policies`)
  instead of a local `Store` under `TOKENOPS_EMBEDDED=1` — these are now the concrete
  demonstration that governance policies configured on the plane reach a live,
  multi-agent run and HALT/steer it (step_cap, cost_budget, output_runaway CANCEL+RETRY,
  tool_output_cap deep swap), not just that the plumbing compiles.

- `Ledger`'s `RunState` renamed `LocalRunState` (#118, locked decision #9) — makes the
  two-tier model explicit ahead of the `LedgerBackend` rewire: this is the per-process
  Tier-1 cache, not the plane's authoritative `run_state`.
- `Ledger.record` no longer writes a zero-delta spend row for non-priced crossings
  (tool calls, un-rolled-up delegates) — a free crossing is a *step*, not spend. The
  cost ledger only moves on priced events (#118).
- **`tests/examples/` (`e2e`-marked) is now part of the default test run and CI**
  (`addopts` narrowed from `-m 'not e2e and not live'` to `-m 'not live'`). These are
  the only tests that drive real servers with real `Governor`/policy HALT/MUTATE
  decisions and a real multi-agent shared ledger — none of the 10 non-`live` ones need
  a network call or API key. Fixes #127: two had gone stale against intentional
  attribution-hardening changes (`28337d1`) without anyone noticing, because they were
  excluded from CI.
  - `test_triad_e2e.py::test_triad_pipeline_completes_with_ledger` — the agent's own
    `intent` (via `instrument_app`) wins over a payload-supplied one; the test asserted
    the old (pre-hardening) precedence.
  - `test_triad_e2e.py::test_triad_cost_not_double_counted_without_parent_rollup` —
    patched a `build_price_book` binding on the wrong module; pricing is resolved in
    `tokenops.control.run`, not re-imported into each example server.
  - `tests/examples/test_bench_e2e.py::test_run_dims_persisted_for_segmentation` →
    renamed `test_run_dims_only_allowlisted_payload_keys_persist` and rewritten to
    assert the intended contract: only allow-listed payload keys (`user_id`/`user`)
    reach `RunRecord.dims`; an arbitrary tag must **not** leak into segmentation
    (`attribution._PAYLOAD_USER_DIM_ALLOWLIST`). The old assertion expected the
    opposite of the hardened, intended behavior.

## [0.2.1] - 2026-09-04

### Changed

- Add configurable short timeout (default 2.0s) for agent card fetch and health checks (#86, thanks [@HeaTTap](https://github.com/HeaTTap))
- Pin `streamlit` to `>=1.38,<2` instead of an unbounded lower-bound-only range (#84, thanks [@SurajPatelPro](https://github.com/SurajPatelPro))
- Declare `pytest-asyncio` as a dev dependency so `make test` passes on a fresh clone

## [0.2.0] - 2026-08-14

### Added

- **HTTP store** when `CONTROL_PLANE_URL` or `TOKENOPS_URL` is set: runs, governance,
  ledger, and run-records go to the AgentPlane control plane over HTTP (`HttpStore`).
  No local SQLite in that mode. `CONTROL_PLANE_API_KEY` / `TOKENOPS_API_KEY` are sent
  as Bearer on those requests.

## [0.1.3] - 2026-07-24

### Fixed

- `register_run` now upserts a dashboard `runs` row so Admin list/detail show the run
  without a separate `create_run`. Ledger spend overlays `cost_micros`; halt/clear
  keep the dashboard row in sync.

## [0.1.2] - 2026-07-24

### Added

- LLM-kind Chronicle `@boundary` / `wrap_llm` runs **pre_call** via `session.on_enter`
  (and ledger admit/complete via `on_leave`). A bare `@boundary(..., kind="llm")` under
  `tokenops_run` is enough for worst-case halt / output-cap MUTATE — no `wrap_complete`
  required. `wrap_complete` still works and opts out of the double pre_call.

### Changed

- Require `agent-chronicle>=0.3.0` (on_enter / on_leave hooks).

## [0.1.1] - 2026-07-24

### Changed

- Require `agent-chronicle>=0.2.0` (was `>=0.1.3`).
- Harden integration UX: ambient run scope and Chronicle `wrap_llm` dispatch for
  `wrap_complete` / streaming paths.

### Added

- Onboarding guide (`docs/guides/onboarding.md`) with prereqs, FAQ, and current limits.
- Broader `wrap_complete` integration coverage for seeded policies.

## [0.1.0] - 2026-07-23

### Added

- Initial PyPI package (`agent-tokenops`): control plane (`python -m tokenops.server`),
  SDK (`wrap_complete`, ledger/policies, Chronicle crossing hook), and Admin UI.
- Default governance seed shipped as package data (`tokenops/config/default.yaml`).

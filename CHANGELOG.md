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
- `Ledger.close_run(run_id)` — drops the per-process `RunState`; called by
  `tokenops_run` on scope exit so a long-lived / shared-governor process does not
  accumulate per-run window state (#115).

### Changed

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

# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `tokenops.repositories.ControlPlaneClient`: a small `httpx` client for control plane 1.0
  ([#162](https://github.com/theagentplane/tokenops/issues/162)): governance with `ETag` /
  `If-None-Match` (the last known configuration is returned, flagged `stale`, when the plane is
  unreachable and one was already fetched), `precheck`, `events:batch`, halt get/set/clear and
  the trace list. Writes are attempted once and never retried (ADR 0002). The governors now run
  on it (see "Changed (breaking)").
- `tests/contract`: contract tests against a real control plane 1.x, run in the CI matrix; the
  same ledger scenarios run against an in-memory fake (`tests/fake_plane.py`) so it cannot drift.

### Changed (breaking)

- **The governors run on control plane 1.0** ([#162](https://github.com/theagentplane/tokenops/issues/162)).
  - `tokenops_run` takes `client=` (a `tokenops.repositories.ControlPlaneClient`, default from
    `CONTROL_PLANE_URL` / `CONTROL_PLANE_API_KEY`) or `config=` (a governance dict, run in
    process with no plane). `store=` is gone. Nothing is registered with the plane: a hop joins
    the Chronicle trace and builds its attribution in memory from its own `intent`,
    `user_dims` and `mode`, so a downstream hop no longer inherits the entry hop's intent.
  - Governance is pulled with an `ETag`. Failure behaviour is explicit: an unreachable plane
    with a configuration already fetched uses that one (logged at WARNING); unreachable with
    none, or no plane and no `config=`, raises, so a hop never runs ungoverned. A failed ledger
    write raises to the caller and is never retried.
  - Budget dimension `run` is now `trace` and the segment key `run:<id>` is `trace:<id>`
    (config, `Budget`, `segment_key`, `concurrency_cap`). Update `dimension: run` in your
    governance YAML.
  - The ledger writes only `spent_add`, `admit`, `complete`, `halt_mark` and `halt_clear`
    (no `step`, no idempotency key). The step window stays in process (control-plane ADR 0009),
    so per-policy statistics such as `context_compaction` savings are visible on the
    `Observation`, not stored by the plane.
  - `python -m tokenops.demo` runs in process; it no longer launches a plane.

- Chronicle 1.0 integration ([#162](https://github.com/theagentplane/tokenops/issues/162)):
  requires `agent-chronicle>=1.0,<2` (pulls `agentplane-primitives==0.2.*`); 0.5 is no longer
  supported. The governor attaches as one `chronicle.Hook` registered on
  `chronicle.default_hooks` (`tokenops.control.crossing.TokenOpsHook`); there is no
  `reset_session` patching and no per-session `on_crossing`/`on_enter`/`on_leave`.
  - `on_enter`, `on_leave` and `on_crossing` now take a `chronicle.CallInfo` (and the live
    result for `on_crossing`) instead of `(boundary_id, kind, input[, result])`.
  - `Throttled` is now a `chronicle.AbortCall` so Chronicle always propagates it; `Halt` stays
    a `BaseException`, which the hook failure policy never swallows.
  - `wrap_complete` / `wrap_stream` pass `provider=` to `wrap_llm`, as Chronicle 1.0 needs it
    for usage and provider on LLM boundaries.
  - Migration: register no hooks yourself; call `tokenops.control.install_crossing_hook()` (done
    for you by `tokenops_run`). Tests that read `session.envelopes` should read envelopes from
    a `chronicle.FunctionHook(record=...)` registered on `default_hooks`.
- `run_id` is gone: the only identifier is `trace_id` (a run is a Chronicle trace). Every
  `run_id` attribute, parameter, keyword, ledger event key and `source_run_id` is now
  `trace_id` / `source_trace_id`. The embedded SQLite schema uses `trace_id` columns; delete
  any local `tokenops.db`. Until the control-plane 1.0 client lands, the HTTP edge translates
  to the control plane 0.2 wire name `run_id` (`http.py`, `http_store.py`,
  `ledger_backend.py`, `client.py`); that translation is deleted with it.
- The `X-TokenOps-Run-Id` and `X-TokenOps-Parent-Span-Id` headers are removed, with
  `TRACE_ID_HEADER`, `PARENT_SPAN_ID_HEADER`, `header_trace_id`, `header_parent_span_id` and
  `tokenops.control.propagate` (`propagation_headers`, `merge_propagation_headers`). A hop
  joins the run through the W3C `traceparent` that Chronicle propagates (`ChronicleMiddleware`,
  `instrument_httpx`, `inject_hosts`). `tokenops_run` opens a Chronicle span from the inbound
  headers when none is active and joins the run registered for that trace id, else registers it
  (`begin_downstream_run` / `begin_entry_run` / `begin_entry_task_run` take `trace_id=` instead
  of `headers=`). Migration: stop sending the TokenOps headers; configure Chronicle's
  `inject_hosts` for peers.
- Known gap: a failure inside the TokenOps hook that is not a `Halt` or `AbortCall` is logged
  and ignored by Chronicle's default hook policy (fail-open). Set
  `chronicle.configure(hooks_fail_call_on_error=True)` to make it fail the call; the default
  stays Chronicle's.

### Removed (breaking)

- The SQLite store (`tokenops.control.store`), `http_store`, the 0.2 `LedgerBackend` /
  `HttpLedgerBackend`, the old `tokenops.control.client.ControlPlaneClient`
  (`from_env`/`register_run`/`require_store`), `tokenops.control.dev_plane`,
  `governance_cache`, run registration (`begin_entry_run`, `begin_downstream_run`,
  `begin_entry_task_run`, `mount_run_registration`, `post_run`), `RunRecord`, `Segment`,
  `BudgetSpec`, `PolicyInstance` and the `contract` extra's `<1.0` pin. Use
  `tokenops.repositories.ControlPlaneClient`; configuration lives in the control plane.
- `tokenops.control.trajectory` and the `trajectory_hint` implementation. The template stays
  known and disabled (it already could not be built); its cross-run index lived in the SQLite
  store and is decided with the policies rework.
- `uvicorn` from the runtime dependencies.

Part of the 1.0 rework ([#162](https://github.com/theagentplane/tokenops/issues/162)). These
duplicated the AgentPlane control plane, which is now the plane and the UI.

- `tokenops.server` (the own FastAPI plane, `python -m tokenops.server`). Run the
  control-plane package instead.
- `tokenops.ui` (Streamlit Admin and Dashboard) and the `streamlit` dependency. Migration:
  use the TokenOps tab of the control plane web page. `policy_label` moved to
  `tokenops.control.policy_labels`.
- `benchmarking/`, the demo/asset `scripts/` (only `scripts/sync-skills.py` stays), the
  `docker-compose*.yml` files, the `Dockerfile`, `.streamlit/`, `docs/notes/` and the binary
  deck under `docs/product/`.
- The example launchers (`examples/run*.py`), `examples/ui/` and the matching `make` targets
  (`control-plane`, `ui`, `run`, `demo*`, `bench-ui`, `db-*`, `stop*`); the examples are
  rewritten against the real control plane in a later pull request.

Still present and removed with the Chronicle 1.0 and control-plane client work: the SQLite
store, run models, ledger backends and `http_store` (they are wired into the governors).

## [0.4.1] - 2026-10-01

No functional changes to the library.

### Added

- Each GitHub Release now includes a CycloneDX SBOM (`agent-tokenops-<version>.cdx.json`)
  listing the resolved dependency tree of a clean install, generated by the same `sbom`
  CI job that runs on every pull request.

### Changed

- CI and release workflows pin every GitHub Action by commit SHA and are audited with
  zizmor in CI.

### Security

- The A2A example server no longer returns exception text in 500 responses.

## [0.4.0] - 2026-09-24

### Changed

- Standardize built-in policy IDs and display labels through one template registry
  and [policy glossary](docs/product/policies-index.md). Admin, Dashboard, and demo
  traces/banners show canonical policy identities; YAML keys, policy class imports, seeded
  `seed_<policy_id>` IDs, and user-configured instance IDs are unchanged
  ([theagentplane/tokenops#53](https://github.com/theagentplane/tokenops/issues/53)).
- `context_compaction` derives compaction capability from `controls.compaction_supported`
  (set by `wrap_complete`) instead of a `has_hook` config flag. The flag is removed from
  governance config — compaction works automatically when using `wrap_complete` (the
  documented integration path). A one-time warning is logged when the policy degrades to
  telemetry (no hook available).
- Chronicle schema 2.0: require `agent-chronicle>=0.5.0,<0.6`. The crossing hooks take `Input` (was `InputState`) and read `input.arguments`; `session.envelopes` replaces the `recorded_envelopes` patch (#149).

### Fixed

- Governance actions now carry optional `Action.policy_id` from the deciding
  detector, so traces report exact policy names instead of guessing from reason
  text. Standalone actions without an ID retain the legacy display fallback.
- Correct the unsupported `tool_freq` catalog reference and stale `tool_reject`
  Compose keys to `tool_fix`, without adding aliases or changing policy params.
  Keep `trajectory_hint` explicitly known-but-disabled across config, UI, and docs;
  existing instances can be disabled in Admin without changing their identity.
- Carry cache-read and reasoning tokens from native SDK responses, bundled adapters,
  and flat agent steps into disjoint `Usage` buckets, avoiding double billing while
  retaining total prompt size for context-compaction trends. Flat dispatch/step
  input and output remain inclusive totals; direct `Usage` producers must exclude
  cached/reasoning subsets from input/output (#137, thanks @kevin-lozada-santos).
  Cache-write premiums and streaming usage remain outside this change.

## [0.3.0] - 2026-09-12

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
  (tool calls, un-rolled-up delegates) — a free crossing is a _step_, not spend. The
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

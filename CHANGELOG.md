# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [2.0.0] - 2026-10-15

Removes what 1.1 deprecated. **No behaviour changed**; only import paths and alias names are
gone. Migration table: [docs/migration-1.x-to-2.0.md](docs/migration-1.x-to-2.0.md).

### Removed (breaking)

- **`tokenops.control`**: the package and every `tokenops.control.<module>` shim. Import from
  `tokenops`, `tokenops.framework`, `tokenops.capabilities`, `tokenops.interfaces` or
  `tokenops.repositories`. *Consumers:* rewrite `tokenops.control.<module>` to the layer that
  owns it (the 1.1 `DeprecationWarning` named the new path).
- The 1.x registration aliases: `RunRegistration`, `RunNotRegisteredError`, `bound.registration`,
  `current_registration`, `bind_registration`, `require_registration` and
  `merge_registration_dims`. *Consumers:* use `HopAttribution`, `NoGovernanceScopeError`,
  `bound.hop`, `current_hop`, `bind_hop`, `require_hop` and `merge_hop_dims`.

## [1.1.0] - 2026-10-15

The governor code is split into the layers `AGENTS.md` describes, and the layering is now
enforced. **No behaviour changed and no 1.0 import broke**: every old path keeps working as a
deprecated shim until 2.0 ([ADR 0006](docs/adr/0006-layered-packages-with-deprecated-shims.md)).

### Added

- `tokenops.framework` (in-process machinery, no network), `tokenops.capabilities`
  (`tokenops_run`, `wrap_complete`, the Chronicle hook) and `tokenops.interfaces`
  (`instrument_app`, HTTP error mapping), each with an `__all__`.
- `LedgerBackend` and `LedgerWriter` protocols (`tokenops.framework`): the ledger depends on
  these, and `ControlPlaneClient` and `LedgerEventWriter` satisfy them.
- `tests/test_layering.py` fails if a layer imports one above it.

### Changed

- `tokenops.control.<module>` is now a deprecated alias of the module's new home (the same
  module object, with a `DeprecationWarning` on import), and `import tokenops.control` warns.
  Import from `tokenops`, or from the layer packages. Removed in 2.0. Where each module went:
  `control/{attribution,boundary,config,context,core,engine,ledger,models,policies,policy_labels,
  pricing,request_context,usage}` is `framework/`; `control/{crossing,integration,ledger_writers,
  run,chronicle_trace_utils}` is `capabilities/`; `control/{http,instrument}` is `interfaces/`.
- The control-plane wire types (`LedgerEvent`, `PrecheckRequest`, `PrecheckResult`,
  `ApplyResult`, ...) are defined in `tokenops.framework.ledger_types`; `tokenops.repositories`
  still exports them.
- Files split by concept: `integration.py` into `complete_wrapper.py`, `stream_wrapper.py`,
  `step_observation.py` and `framework/message_steering.py`; `ledger.py` into `budget.py`,
  `ledger_events.py` and `ledger.py`. `capabilities/integration.py` remains as a re-export.
- `mypy --strict` flags are enforced on the four layered packages.

## [1.0.1] - 2026-10-15

### Fixed

- **Governance silently off under `chronicle.instrument_httpx()`.** TokenOps' own control-plane
  requests were recorded as crossings, which re-entered the governor hook and called the plane
  again; Chronicle swallowed the resulting recursion as a hook failure and the run went
  ungoverned (no spend, no budget trips). Plane requests now carry `chronicle.internal`, so
  Chronicle skips them.

### Changed

- The "registration" vocabulary is renamed, because nothing is registered (a run is a trace):
  `RunRegistration` is `HopAttribution`, `RunNotRegisteredError` is `NoGovernanceScopeError`,
  `bound.registration` is `bound.hop`, and `current_registration`, `bind_registration`,
  `require_registration` and `merge_registration_dims` are `current_hop`, `bind_hop`,
  `require_hop` and `merge_hop_dims`. The old names remain as aliases in 1.x.
- The example servers configure tracing (`examples/a2a/tracing.py`) and are verified end to end
  against a real control plane (`tests/e2e`): triad, research to summarize, and brief.

### Removed

- The `trajectory_hint` template: it could not be enabled and the control plane never accepted
  it ([ADR 0005](docs/adr/0005-remove-trajectory-hint.md)). A configuration naming it now fails
  with `unknown policy`. Also removed as unused: `bind_governance`, `current_bound_run` and
  `CallRequest.primary_agent_turn`.

## [1.0.0] - 2026-10-15

TokenOps 1.0 is the **governors only**: policies, budgets and halts, attached to
[Chronicle](https://github.com/theagentplane/chronicle) 1.x and the AgentPlane
[control plane](https://github.com/theagentplane/control-plane) 1.x. It stops carrying its own
server, store, UI and run model. A run is a Chronicle trace; the only identifier is `trace_id`.
Delivered as the series in [#162](https://github.com/theagentplane/tokenops/issues/162).
**Every entry is classified; the per-consumer migration is in
[docs/migration-0.4-to-1.0.md](docs/migration-0.4-to-1.0.md).**

Requires `agent-chronicle>=1.1,<2`, `agentplane-primitives==0.2.*` and a control plane `>=1.0`
(only where you run one; `>=1.0.1` to configure a `time_budget` policy there).

### Changed (breaking)

- **A run is a trace.** `run_id` is `trace_id` everywhere (attributes, parameters, ledger event
  keys, `source_run_id`). *Consumers:* rename it.
- **The TokenOps headers are removed**: `X-TokenOps-Run-Id` and `X-TokenOps-Parent-Span-Id`,
  `TRACE_ID_HEADER`, `PARENT_SPAN_ID_HEADER`, `header_trace_id`, `header_parent_span_id` and
  `tokenops.control.propagate`. Hops share a run through the W3C `traceparent` that Chronicle
  sends. *Consumers:* configure `chronicle.configure(inject_hosts=[...])` and
  `chronicle.instrument_httpx()`.
- **No run registration.** `tokenops_run` joins the Chronicle trace and builds attribution in
  memory from the hop's own `intent`, `user_dims` and `mode`; a downstream hop no longer
  inherits the entry hop's intent. `begin_entry_run`, `begin_downstream_run`,
  `begin_entry_task_run`, `mount_run_registration` and `post_run` are removed.
- **`tokenops_run(client=..., config=...)`**: `client=` is a
  `tokenops.repositories.ControlPlaneClient` (default from `CONTROL_PLANE_URL` and
  `CONTROL_PLANE_API_KEY`), `config=` is a governance dict run in process with no plane.
  `store=` is gone. *Consumers:* replace `TOKENOPS_URL` with `CONTROL_PLANE_URL`.
- **Configuration lives in the control plane.** Governance is pulled with an `ETag`; there is no
  local seed. The budget dimension `run` is `trace` and the segment key `run:<id>` is
  `trace:<id>` (config, `Budget`, `segment_key`, `concurrency_cap`). *Consumers:* change
  `dimension: run` to `dimension: trace` in governance YAML.
- **Chronicle 1.x hooks.** The governor is one `chronicle.Hook` on `chronicle.default_hooks`
  (`TokenOpsHook`); there is no `reset_session` patching. `on_enter`, `on_leave` and
  `on_crossing` take a `chronicle.CallInfo`. `Throttled` is a `chronicle.AbortCall`; `Halt` stays
  a `BaseException`. `wrap_complete` and `wrap_stream` pass `provider=` to `wrap_llm`.
- **The ledger writes only** `spent_add`, `admit`, `complete`, `halt_mark` and `halt_clear`: no
  `step` event and no idempotency key (control-plane ADR 0007 and 0009). The step window stays in
  process, so `step_cap` and `progress_guard` see this process's steps for the trace
  ([ADR 0004](docs/adr/0004-policy-state-lives-in-process-except-shared-spend.md)).
- **Failure behaviour is explicit.** A configuration fetched earlier is used when the plane is
  unreachable (WARNING `tokenops.governance_stale`); with none, or no plane and no `config=`,
  `tokenops_run` raises, so a hop never runs ungoverned. A failed synchronous ledger write
  raises and is never retried
  ([ADR 0002](docs/adr/0002-ledger-writes-are-attempted-once.md)).
- **Ledger writes are asynchronous by default.** With a plane, `spent_add` and `complete` are
  queued and sent from a background `LedgerEventWriter`; `admit` and halt writes stay
  synchronous and reads wait (bounded) for this process's own queued writes. A batch is retried
  only on a failed connect, never on an unknown outcome, and a full queue or unreachable plane
  drops and counts events (`LedgerEventWriter.stats`), so an outage can understate spend
  ([ADR 0003](docs/adr/0003-ledger-spend-writes-are-asynchronous.md)). *Consumers:*
  `tokenops_run(async_writes=False)` restores a synchronous write per crossing; call
  `tokenops.flush_ledger_writes()` before a short-lived process exits (also done at exit).
- `agent-chronicle` is `>=1.1,<2` and the active span is read with the public
  `chronicle.current_session()`.
- `python -m tokenops.demo` runs in process; it no longer launches a control plane.

### Removed (breaking)

- `tokenops.server` (the own FastAPI plane), `tokenops.ui` (Streamlit), the `streamlit` and
  `uvicorn` dependencies, `Dockerfile`, `docker-compose*.yml`, `benchmarking/`, the demo and
  asset scripts (only `scripts/sync-skills.py` stays), the example launchers and `examples/ui`,
  and the matching `make` targets. *Consumers:* run the control plane and use its web page.
- The SQLite `Store`, `HttpStore`, the 0.2 `LedgerBackend` / `HttpLedgerBackend`, the old
  `tokenops.control.client.ControlPlaneClient`, `dev_plane`, `governance_cache`, `RunRecord`,
  `Segment`, `BudgetSpec` and `PolicyInstance`. Delete any local `tokenops.db`.
- `tokenops.control.trajectory` and the `trajectory_hint` implementation. The template stays
  known and disabled (it could not be built before either); re-homing it is undecided.
- The `contract` extra no longer accepts control plane 0.x (`agentplane-control-plane>=1.0.1`).

### Added

- `tokenops.repositories.ControlPlaneClient`: a small `httpx` client for control plane 1.0:
  governance with `ETag` / `If-None-Match`, `precheck`, `events:batch`, halt get, set and clear,
  and the trace list.
- `LedgerEventWriter`, one per client and shared by every hop of a process.
- `context_compaction` savings are recorded as envelope metadata
  (`tokenops.compaction_tokens_before`, `_after`, `_saved`), because the plane stores no
  per-policy statistics.
- `tests/contract` and `tests/e2e` against a real control plane 1.x: a governed agent trips its
  budget and the halt is on the trace; two agents share one budget; a halted trace is replayed
  with the fix. A fake plane (`tests/fake_plane.py`) is verified by the same contract suite.
- Conventions: `AGENTS.md`, `docs/adr/` (ADRs 0001 to 0004), CODEOWNERS, DCO and PR-size
  checks, CodeQL, dependabot, Windows and Python 3.13 in the CI matrix, a build and wheel check,
  PEP 735 dependency groups for the dev tooling, and a `py.typed` marker.
- The documentation is rewritten for 1.0, with a migration note.

### Known limits

- `wrap_complete` and `wrap_stream` are still TokenOps wrappers around `chronicle.wrap_llm`
  ([#173](https://github.com/theagentplane/tokenops/issues/173)).
- The control plane on SQLite can answer a TokenOps agent and Chronicle writing at once with
  `database is locked` ([control-plane#28](https://github.com/theagentplane/control-plane/issues/28)).
- `src/tokenops/` is not yet split into the framework, repositories, capabilities and interfaces
  layers, and `mypy --strict` is not enforced.
- The example servers are not yet re-verified against a control plane 1.x.

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

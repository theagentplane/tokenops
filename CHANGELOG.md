# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

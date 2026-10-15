# 0006. Layered packages, with the 1.0 paths kept as deprecated shims

| Field | Value |
|---|---|
| Status | Proposed |
| Date | 2026-10-15 |
| Deciders | Susheem Koul, Tisha Chawla |

## Context

Through 1.0 all governor code lived in one package, `tokenops.control`, and the layering in
`AGENTS.md` (framework, repositories, capabilities, interfaces) was a target the tree did not
meet. In particular the in-process ledger imported the control-plane client, so the framework
was not free of I/O, and nothing stopped a lower layer from importing a higher one. Users and the
repository's own tests import deep paths such as `tokenops.control.core`.

## Options considered

### Option A: leave `tokenops.control` as is

- Good: no churn.
- Bad: the stated layering stays unenforced; the framework keeps a hard dependency on the HTTP
  client; files over 400 lines stay mixed concept bags.

### Option B: move to layered packages and break the old paths

- Good: the cleanest tree.
- Bad: breaks every deep import in a minor release, for no behavioural gain.

### Option C: move to layered packages and keep the old paths as deprecated shims

- Good: the layering is real and tested; imports from 1.0 keep working for the 1.x series.
- Bad: a second, deprecated import tree to maintain until 2.0.

## Decision

We will move the code into `tokenops.framework`, `tokenops.capabilities` and
`tokenops.interfaces` beside the existing `tokenops.repositories` (Option C).

- Each old module under `tokenops.control` becomes a shim that replaces itself in `sys.modules`
  with the new module and emits a `DeprecationWarning`, so `tokenops.control.core is
  tokenops.framework.core` and patching either path affects both. `tokenops.control` itself
  re-exports the 1.0 public names and warns on import. Everything is removed in 2.0.
- The framework reaches the control plane only through the `LedgerBackend` and `LedgerWriter`
  protocols (`framework/ledger_backend.py`), which `ControlPlaneClient` and `LedgerEventWriter`
  satisfy. The wire types (`LedgerEvent`, `PrecheckRequest`, ...) moved to
  `framework/ledger_types.py`; `tokenops.repositories` re-exports them.
- `tests/test_layering.py` fails if a layer imports one above it, or if anything outside
  `tokenops.control` imports it. The four layered packages are held to `mypy --strict`.

## Consequences

- **Good:** the layering in `AGENTS.md` is true and enforced; the framework has no network client.
- **Bad or risky:** a patch target that names a deep 1.0 path still works only because of the
  `sys.modules` alias; code that held a reference to a private helper that moved (for example
  `_compact_messages`, now `framework.message_steering.compact_messages`) must be updated.
- **Follow-ups:** remove `tokenops.control` in 2.0. `wrap_complete` onto Chronicle hooks is #173.

## Impact on other repositories

None. The public names exported from `tokenops` are unchanged.

## Links

- [ADR 0001](0001-record-architecture-decisions.md)
- Issue 162, section 5

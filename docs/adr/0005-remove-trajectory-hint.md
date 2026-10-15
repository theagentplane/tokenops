# 0005. Remove the `trajectory_hint` template

| Field | Value |
|---|---|
| Status | Proposed |
| Date | 2026-10-15 |
| Deciders | Susheem Koul, Tisha Chawla |

## Context

`trajectory_hint` injects a playbook from prior successful runs. It is the only cross-run
policy: it needs a persistent index of earlier traces. In 0.4 that index lived in TokenOps'
SQLite store, and the policy had already been disabled in `build_governor` (it raised "temporarily
disabled") because the HTTP control plane did not serve the routes it needed. TokenOps 1.0
removed the store and the implementation. The control plane stores no step window and no
per-policy statistics (control-plane ADR 0009), and its template allow-list never included
`trajectory_hint`, so no configuration written to the plane can name it. Its own measurements also
showed that indexing on structure alone can mislead (the Phase 1 learnings in the old
`docs/policies/trajectory_hint.md`).

## Options considered

### Option A: keep a disabled template

- Good: a configuration that names it gets a specific message.
- Bad: a template with no implementation, a "disabled" code path nothing else uses, and a docs
  page for something that cannot be enabled.

### Option B: remove it

- Good: one fewer concept; the template list equals what can run; an old configuration fails with
  the same "unknown policy" error as any other unsupported name.
- Bad: re-introducing it later needs a new design (where the index lives, a quality gate).

## Decision

We will remove the `trajectory_hint` template and its documentation page (Option B). The Phase 1
design and learnings remain in the git history of 0.4.x. Re-introducing it is a new proposal.

## Consequences

- **Good:** the policy list, the code and the control plane's allow-list agree.
- **Bad or risky:** a governance file that still names `trajectory_hint` fails with
  `unknown policy`. It could not have worked on 1.0 either (it raised "temporarily disabled").
- **Follow-ups:** none.

## Impact on other repositories

control-plane: none (its allow-list never included it).

## Links

- [ADR 0004](0004-policy-state-lives-in-process-except-shared-spend.md)
- Issue 162, section 4

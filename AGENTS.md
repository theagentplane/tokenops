# Agent instructions

TokenOps is the governance layer of the AgentPlane suite: it decides, inside an agent's own
process, whether the next LLM call may happen (budgets, caps, halts, steering), using Chronicle
hooks and the control plane's ledger. It is being reworked into **the governors only**; it will
stop carrying its own control plane, run model, store and UI
([issue 162](https://github.com/theagentplane/tokenops/issues/162)).

This file is read by AI coding agents (Claude Code, Codex, Cursor, Copilot and others). Humans
may find it useful too.

## Source of truth

- The rework plan and the decisions already taken are in
  [issue 162](https://github.com/theagentplane/tokenops/issues/162). Do not re-litigate them; if
  the code and the plan disagree, stop and ask.
- The entities (`Trace`, `Span`, `Envelope`, `Usage`) come from
  [`agentplane-primitives`](https://github.com/theagentplane/primitives). **Never define a local
  copy of an entity.** A run is a Chronicle trace: the only identifier is `trace_id`, there is
  no `run_id`.
- Governance configuration lives in the control plane database and is pulled with an `ETag`.
  A gap in Chronicle or the control plane is an issue in that repository, not a workaround here.

## Architecture decisions

Decisions that shape this repository are recorded as ADRs in [`docs/adr/`](docs/adr/README.md).

- **Before changing architecture,** read the ADRs: structure, public interfaces, data formats,
  dependencies or anything shared with another repository. Do not undo an accepted decision
  silently. If a change conflicts with one, say so and propose a new ADR that supersedes it.
- **When asked to record a decision,** or when you make one that meets the criteria in
  `docs/adr/README.md`, write an ADR: copy `docs/adr/template.md`, use the next free number,
  keep it to about a page, and add it to the index.
- **Do not invent reasoning.** If you do not know why something was decided or which
  alternatives were weighed, ask. Leave the status as *Proposed*: the people named as deciders
  accept it.
- **Never rewrite an accepted ADR.** Supersede it with a new one.

## Layers

Each layer imports only from the ones above it; `tests/test_layering.py` enforces it.
The 1.0 package `tokenops.control` was removed in 2.0; import from the layers.

| Layer | Package | Rule |
|---|---|---|
| Primitives | `agentplane_primitives` (external) | Data only. |
| Framework | `tokenops.framework` | In-process machinery: policies, pricing, governor. **No network.** |
| Repositories | `tokenops.repositories` | The **only** place that does I/O: the control-plane client. |
| Capabilities | `tokenops.capabilities` | Governed-run workflows. |
| Interfaces | `tokenops.interfaces`, `tokenops.__init__` | What the developer touches. |

## Code layout and style

- `src` layout, typed package (`py.typed`), Python 3.10 to 3.13 (no syntax newer than 3.10).
- One concept per file, with a module docstring that says what it is. Folders are named for what
  they hold; helper modules are suffixed for what they are (`*_utils.py`, `*_types.py`,
  `*_repository.py`). `__init__.py` re-exports the public names with `__all__`.
- Types and models, and functions, live apart: no functions in model modules, no models in utils.
- Must work on Windows and Linux. On Windows use `python -m pytest`.
- Tooling: `ruff` (line length 100), `mypy`, `pytest`. Developer tools are the `dev` dependency
  group (`pip install --group dev`), not a published extra. Run the checks listed in
  [CONTRIBUTING.md](CONTRIBUTING.md) before you finish.

## Invariants (do not break)

- **Fail-safe is explicit:** what happens when the control plane is unreachable is a documented,
  tested behaviour, never an accident of an exception.
- **No double counting:** ledger events are not deduplicated by the plane, so a retry must never
  be able to write the same spend twice.
- **A halt stops the next call, not the current one:** governors act by raising
  `chronicle.AbortCall` before a call; they never swallow or rewrite the caller's real result.
- **Dollars are written in micro-USD from one price source.** Do not add a second price table.

## Change size

- **Estimate before writing code:** lines added plus removed, not counting generated files,
  lockfiles, golden test data or pure moves, renames and deletions.
- **If the estimate is above 400 lines, stop and plan.** Propose to the user a short plan that
  splits the work into logical components (each reviewable on its own, passing CI, in order), and
  wait for agreement before implementing. Open one pull request per component.
- **Keep one change as one thing.** Do not mix unrelated changes into a pull request.
- Staying above 400 lines is acceptable for boilerplate, mechanical changes or generated code,
  or when the maintainer has decided on one change, but say why in the pull request description.

## Related repositories

[chronicle](https://github.com/theagentplane/chronicle) (edge SDK: record, save, replay) ·
[primitives](https://github.com/theagentplane/primitives) (shared schemas) ·
[control-plane](https://github.com/theagentplane/control-plane) (storage, query, UI) ·
[tokenops](https://github.com/theagentplane/tokenops) (cost governance)

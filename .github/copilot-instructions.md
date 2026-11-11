# Copilot instructions

Follow [AGENTS.md](../AGENTS.md); it is the source of truth for this repository (layers, invariants,
change size, style). The points below are the ones most often missed.

## Architecture decision records (required for feature additions)

- **Every feature addition needs an ADR in the same pull request.** A feature addition is a new or
  changed policy, policy parameter, configuration key or public API. Bug fixes, renames and small
  refactors do not need one.
- Write it in `docs/adr/`: copy `docs/adr/template.md`, use the next free number, keep it to about a
  page, set the status to *Proposed*, and add a row to the index in `docs/adr/README.md`.
- Do not invent reasoning or alternatives. Take them from the linked issue; if they are not
  there, ask. Never rewrite an accepted ADR; supersede it with a new one.
- If a change conflicts with an accepted ADR, say so and propose a superseding ADR.
- When reviewing a pull request that adds a feature without an ADR, ask for one.

## Before you finish

Run `ruff check`, `ruff format --check`, `mypy` and `python -m pytest` (see CONTRIBUTING.md), and add
a CHANGELOG entry.

# Architecture Decision Records

An ADR is a short note that records **one decision**: what we chose, why, what else we
considered, and what it costs us. We keep them in the repository so the reasoning stays next to
the code and survives people changing teams.

## When to write one

Write an ADR when a decision:

- changes how the system is structured (modules, layers, who owns what),
- changes a public interface, a data format or a schema,
- adds, removes or replaces a significant dependency or tool,
- is hard or expensive to reverse, or
- affects another repository (chronicle, primitives, control-plane, tokenops).

Do not write one for routine changes: a bug fix, a rename, a small refactor.

## How to write one

1. Pick the next number: look at the files in this folder and add one to the highest.
2. Copy [template.md](template.md) to `NNNN-short-kebab-title.md`.
3. Fill it in. Keep it to about one page.
4. Open a pull request. Start with status **Proposed**; set **Accepted** when the people
   named as deciders agree.
5. Add a row to the index below.

## Rules

- **An accepted ADR is not rewritten.** Fixing a typo is fine. To change a decision, write a new
  ADR that says it supersedes the old one, and update only the old ADR's status line and link.
- **One decision per ADR.**
- **Say what we gave up.** Every real decision has a cost; if the Consequences section lists
  only good things, it is not finished.
- **Decisions that span repositories** are recorded in the repository that owns the decision. The
  "Impact on other repositories" section says what must change elsewhere, and the other
  repositories link to the ADR.

## Index

| ADR | Title | Status |
|---|---|---|
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions | Accepted |
| [0002](0002-ledger-writes-are-attempted-once.md) | Attempt each ledger write once; never retry an unknown outcome | Proposed |

Decisions taken in the suite for the 1.0 rework (trace as run, governance pulled from the
database, halt as a trace attribute, no deduplication of ledger events, ledger counters) are
owned by the control-plane and Chronicle repositories; see
[issue 162](https://github.com/theagentplane/tokenops/issues/162) for the links. TokenOps ADRs
for its own decisions are added with the pull requests that make them.

Related repositories: [chronicle](https://github.com/theagentplane/chronicle), [primitives](https://github.com/theagentplane/primitives),
[control-plane](https://github.com/theagentplane/control-plane), [tokenops](https://github.com/theagentplane/tokenops).

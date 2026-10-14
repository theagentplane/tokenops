---
name: adr
description: Write or update an Architecture Decision Record in docs/adr. Use when a decision affects structure, a public interface, a data format, a dependency, or another repository, or when asked to "record a decision" or "write an ADR". Also use before proposing a change that might conflict with an existing ADR.
---

# Writing an Architecture Decision Record

ADRs live in `docs/adr/`. The rules and index are in `docs/adr/README.md`; the template is
`docs/adr/template.md`. Read the README first.

## 1. Decide whether an ADR is needed

Write one when the decision changes structure, a public interface, a data format or schema, a
significant dependency or tool, is hard to reverse, or affects another repository. Do not write
one for a bug fix, a rename or a small refactor. If unsure, ask the user.

## 2. Check what already exists

List `docs/adr/`. Read ADRs that touch the same area. If the new decision conflicts with an
accepted ADR, it must supersede it explicitly; do not quietly contradict it.

## 3. Create the file

- Number: the highest existing `NNNN` plus one, zero-padded to four digits.
- Name: `docs/adr/NNNN-short-kebab-title.md`. The title states the decision in present tense
  ("Use X for Y"), not the topic ("Y storage").
- Copy `docs/adr/template.md` and fill it in.

## 4. Fill it in honestly

- **Context:** verifiable facts only. Read the code or documents rather than guessing.
- **Options considered:** the real alternatives, each with honest good and bad points.
- **Decision:** one clear sentence, then the reasons that decided it.
- **Consequences:** include what gets worse or riskier. An ADR with only benefits is unfinished.
- **Impact on other repositories:** list each affected repo (chronicle, primitives,
  control-plane, tokenops) and what must change there, or write "none".
- Keep it to about one page; link to longer material.
- **If you do not know the reasoning or the alternatives that were weighed, ask the user.**
  Never invent rationale.

## 5. Status and people

- Set status to **Proposed**. Only set **Accepted** when the user says the decision has been
  made, and then record who decided in the Deciders field. Use the names of people, not "Claude".
- Set the date to today.

## 6. Update the index

Add a row to the index table in `docs/adr/README.md`.

## 7. Superseding or changing a decision

- Never rewrite an accepted ADR's content. Fixing a typo is fine.
- Write a new ADR, set its "Supersedes" field, and in the old ADR change only the status to
  **Superseded** and add a "Superseded by" link.

## 8. Report back

Tell the user the file path, the one-sentence decision, and any open question you could not
answer without them.

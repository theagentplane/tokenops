# 0001. Record architecture decisions

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-10-05 |
| Deciders | Susheem Koul, Tisha Chawla |

## Context

Four repositories (chronicle, primitives, control-plane, tokenops) now evolve together and share
contracts. Decisions are made in conversations, pull request threads and long design documents,
and the reasoning is hard to find afterwards. New contributors, and AI coding agents working in
these repositories, have no reliable way to learn why something is built the way it is, so they
can unknowingly undo a deliberate choice.

## Options considered

### Option A: keep decisions inside design documents and pull requests

- Good: no new process.
- Bad: reasoning is scattered, mixed with implementation detail, and edited over time, so the
  record of what was decided and when is lost.

### Option B: one ADR per decision, stored in each repository

- Good: small, dated, reviewable records next to the code; easy for agents to read; history
  shows what changed and why.
- Bad: a little writing discipline is needed, and cross-repository decisions need a rule about
  where they live.

## Decision

We will record architecture decisions as ADRs in `docs/adr/` of each repository, using the
template in this folder. Cross-repository decisions are recorded in the repository that owns the
decision and linked from the others. AI coding agents are told to read the ADRs before changing
architecture and to follow `docs/adr/README.md` when asked to record a decision.

## Consequences

- **Good:** decisions are findable and dated; superseded decisions stay visible.
- **Bad or risky:** ADRs go stale if nobody writes them, so writing one is part of making a
  qualifying decision, not a follow-up.
- **Follow-ups:** backfill ADRs for the decisions already taken in the Chronicle technical
  design document where they matter most.

## Impact on other repositories

The same folder, template and agent instructions are added to chronicle, primitives,
control-plane and tokenops.

## Links

- [How to write an ADR](README.md)
- [Template](template.md)

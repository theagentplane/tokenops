---
name: raise-issue
description: >-
  Write a GitHub issue for the TokenOps repo that a newcomer can act on: context
  on how the relevant machinery works, the problem with verified code paths, a
  proposed approach, and explicit tradeoffs and non-scope. Use when filing a bug,
  a design proposal, or an epic against theagentplane/tokenops, or when asked to
  turn a finding, a debugging session, or a design discussion into an issue.
---

# Raise a TokenOps issue

An issue is read by someone who has never opened this repo. They should be able
to go from the title to a first commit without asking anyone a question.

Write every issue in four sections, in this order.

| Section | Answers | Failure if skipped |
|---|---|---|
| **Context** | What is this part of TokenOps, and how does it work? | Reader cannot tell whether the behaviour is a bug or the design |
| **Problem** | What is wrong, shown in code and observed output? | Reader debates whether the problem is real |
| **Proposed approach** | What should change, concretely? | Issue becomes a complaint, not work |
| **Tradeoffs / non-scope** | What was rejected, and what this is not? | Reviewer relitigates settled choices; scope creeps |

---

## The rule behind the rules

**Assume the reader knows nothing about this repo.** Not the vocabulary, not the
call flow, not why a run differs from a request. TokenOps has a small number of
load-bearing concepts that every file assumes and no file explains. An issue that
opens with "`pre_call_worst_case` fails closed on unknown models" is unreadable to
anyone who has not already lost an afternoon to the codebase.

**Verify every claim against source before writing it.** Cite `file.py:line`.
Read the line first. A confident wrong reference is worse than no reference,
because the reader trusts it and then cannot find the thing.

---

## 1. Context

Enough for a newcomer to understand the machinery the issue touches, and no more.

- **One sentence on what TokenOps does**, then narrow to the subsystem. "TokenOps
  caps spend for a whole agent workflow and enforces it before every model call"
  &rarr; "the cap is computed by a price function, built once per run".
- **Define the terms your issue uses.** Pull from this list; define only what you
  actually mention:

  - **run** &mdash; one whole workflow, not one request. Shares a `run_id` and one ledger.
  - **`tokenops_run()`** &mdash; opens or joins a run, returns a `bound` handle.
  - **`wrap_complete()`** &mdash; wraps the model call. The enforcement point.
  - **Ledger** &mdash; records spend, holds the halt flag.
  - **Policy** &mdash; a (detect, fix) pair, e.g. `cost_budget`, `step_cap`.
  - **Governor** &mdash; runs the policies, built per run from governance config.
  - **`Halt`** &mdash; raised to abort a run; extends `BaseException` on purpose.
  - **`Micros`** &mdash; integer micro-USD, `$1.00 == 1_000_000`. No floats in the cost path.
  - **`PriceFn`** &mdash; `(provider, model, Usage) -> Micros`.
  - **control plane** &mdash; the shared server; without it the ledger is per-process.

- **Show the call flow** if the issue depends on ordering. A numbered list of
  steps with the file for each beats prose. State which steps run before the
  provider is contacted and which after &mdash; a surprising number of TokenOps
  bugs turn on that boundary.
- **Quote the code that defines current behaviour**, with its path, rather than
  describing it.

Do not include history, rationale for how the code got this way, or a tour of
files the issue does not touch.

## 2. Problem

- **Lead with the observable failure**, not the internal cause. Paste real output
  &mdash; an error, a trajectory, a log line, a test result. Redact keys.
- **Then walk to the cause**, one frame at a time, with paths.
- **Say what the user sees versus what is actually happening.** A large share of
  the pain in this codebase is a correct mechanism reporting itself badly: a
  fail-closed price lookup surfaces as `run already halted`, which is
  indistinguishable from a legitimate budget stop. Call that out explicitly when
  it applies; it is often a bigger fix than the mechanism itself.
- **Quantify the blast radius.** Which providers, which configurations, how many
  users. "Every non-OpenAI, non-Anthropic model" is actionable; "some models" is not.
- **Distinguish correct-but-unhelpful from wrong.** If the behaviour is by design,
  say so and quote the invariant (e.g. `control/core.py:18`), then argue about the
  ergonomics. Reviewers push back hard on issues that read as if a deliberate
  safety property were an accident.

## 3. Proposed approach

- **Name the shape before the detail.** One or two sentences the reader can repeat
  back, e.g. "rates become data attached to a run, resolved through an ordered chain".
- **Show the concrete artefact** &mdash; the config, the JSON, the signature. Real
  values, not placeholders.
- **Phase it** when the work splits. For each phase: what it contains, what it
  touches, and whether it needs a migration. Say which phase alone would close the
  issue for most users.
- **Say what stays the same.** Reviewers need to know the change is additive, or
  exactly where it is not.
- **Keep recommendations attached to open questions.** An open question with no
  recommendation stalls; a recommendation with no question hides a decision.

## 4. Tradeoffs / non-scope

The section most often skipped and most often needed.

- **Tradeoffs accepted** &mdash; what the proposal gives up, and why that is the
  right trade. If a simpler option was rejected, name it and say why, so nobody
  proposes it again in review.
- **Explicitly out of scope** &mdash; adjacent problems this issue does *not*
  solve. Link the issue that owns each one, or say a new issue is needed. Readers
  will assume an issue covers everything nearby unless told otherwise.

Both halves exist to stop the same two failures: relitigating settled decisions,
and scope growing until nothing ships.

---

## Checks before filing

```
- [ ] A reader who has never opened this repo can follow section 1
- [ ] Every file:line was read, not recalled
- [ ] Observed output is pasted, not paraphrased; secrets redacted
- [ ] Blast radius is quantified
- [ ] Deliberate behaviour is named as deliberate, with the invariant quoted
- [ ] The proposal has a concrete artefact, not just a direction
- [ ] Open questions carry recommendations
- [ ] Out-of-scope items link an issue or ask for one
- [ ] Searched open issues for overlap; cross-referenced neighbours
- [ ] Title states the problem, not the solution
```

## Titles

State the defect and its consequence. The reader is scanning fifty rows.

- Good: `Pricing table is a hardcoded 5-model dict: load rates from user JSON or an external price source`
- Good: `Inflight ledger is a bare per-segment counter — not safe under async/batched/retried admit·complete`
- Weak: `Improve pricing` &mdash; no defect, no consequence
- Weak: `Add TOKENOPS_PRICES env var` &mdash; a solution with the problem hidden

## Labels

`bug` for wrong behaviour, `enhancement` for new capability or design,
`documentation` when the fix is words. Add `good first issue` only when context,
approach and acceptance are all concrete enough for someone with no repo history
to finish it unaided.

## Worked example

`#128` (pricing table) follows this structure end to end: context establishes the
run model and where `PriceFn` sits, problem shows the halted trajectory before
naming `pricing.py:53`, approach gives the resolution chain and the JSON, and
non-scope pushes failure postures to `#129` and gateway model selection to a new
issue.

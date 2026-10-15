# Trajectory hint

*Warm-start INJECT from prior successful runs.*

**Policy ID:** [`trajectory_hint`](../product/policies-index.md)

> **⛔ DISABLED, and the implementation is removed.**
> `config.build_governor` refuses a config that contains `trajectory_hint`. It is the only
> cross-run policy: it needs a persistent index of prior traces, which the control plane does
> not serve (it stores no step window and no per-policy statistics, control-plane ADR 0009),
> and its Phase-1 quality gates are known to be insufficient (see Learnings). The SQLite store
> that held the index, `tokenops.control.trajectory` and the policy module were removed in
> TokenOps 1.0; they remain in the git history of 0.4.x.
> Re-enabling it is a design decision (where the index lives, and a quality gate); the template
> name stays reserved so a configuration naming it fails clearly.

Companion to [`halt.md`](../halt.md). **Cannot be enabled through configuration.**

The sections below describe the Phase 1 design and historical experiments, not a supported
configuration.

---

## TL;DR

On the **first primary-agent LLM call** of a run, lookup prior successful runs with a similar
first-line task (exact hash + SimHash) within a configured **scope**. If matched, **INJECT** a
compressed playbook — tool order, cost, pitfalls — as a final user turn. Never HALTs.

Index rows are built **in the background** after run close (enqueue on the response path,
compress in a daemon drain worker).

**Not in ``default.yaml``.** The configuration below is a historical reference, not a
supported opt-in: ``build_governor`` rejects ``trajectory_hint`` even with ``enabled: false``.

## Detect (formula)

```
pre_call AND (primary_agent_turn OR steps == 0) AND NOT halted
lookup(scope_key, normalize(task)) within max_age_days:
  T1: input_hash exact match
  T2: SimHash hamming ≤ threshold
skip inject if indexed step_count < min_index_steps
```

## Scope key

```
scope_key = sorted join of dim=value for each configured scope_dim:
  intent  → the hop's `intent`
  agent   → boundary service
  <tag>   → the hop's `user_dims[<tag>]` or "_none"
```

Default ``scope_dims: [intent, agent]``. No hardcoded tenant.

## Index write (structural gates)

Enqueued at run close when ``enabled: true`` and all pass:

- ``status == completed``
- ``halt_reason`` is null
- ``steps >= min_steps``
- ``cost_micros > 0``
- normalized task length ≥ ``min_input_chars``

**Phase 2:** ``quality_score`` / constraint-adherence hook — see Learnings.

## Action — INJECT once

Hint is pinned during ``context_compaction`` (same as ``progress_guard`` corrections).

**Injection gate:** skip if indexed ``step_count < min_index_steps`` (default 4) — short
trajectories rarely benefit from hint overhead.

**Tiered format** (from indexed step count):

| Tier | Steps | Payload |
|------|-------|---------|
| ``sequence_only`` | ≤ ``sequence_only_max_steps`` (6) | tool path only |
| ``sequence_plus_pitfalls`` | ≤ ``sequence_plus_pitfalls_max_steps`` (12) | path + brief pitfalls |
| ``full`` | > 12 | path + step summary + pitfalls |

## Historical config (currently rejected)

Omit `trajectory_hint` from `governance.policies` in shipped configurations.
This reference block is rejected even with `enabled: false`; it is not an enablement recipe.

```yaml
trajectory_hint:
  enabled: false              # historical opt-in flag; config currently rejected
  scope_dims: [intent, agent]
  max_age_days: 30            # mandatory
  max_entries_per_scope: 500
  simhash_threshold: 4
  min_steps: 2                # index write gate
  min_index_steps: 4          # inject gate (indexed step count)
  sequence_only_max_steps: 6
  sequence_plus_pitfalls_max_steps: 12
  min_input_chars: 10
  hint_max_chars: 1600
```


## Learnings (live bench, Phase 1)

### When hints help vs hurt

| Scenario | Indexed steps | Hint fired? | Cost delta vs steering |
|----------|---------------|-------------|------------------------|
| ``example_tight_cap`` | 2 | No (``min_index_steps``) | ~0% — correct skip |
| ``books_pagination_stress`` | 7–21 | Yes (exact / simhash) | Often **negative** — hint did not shorten runs |

**Takeaway:** matching + injecting is not enough. Cost savings require trajectories long enough
to repay hint tokens *and* playbooks that encode constraint-faithful behavior.

### Short trajectories — skip inject

``min_index_steps: 4`` prevents firing on 2-step tasks where hint overhead dominates
(``example_tight_cap``: prior +0.3% cost with hint; after gate, 0% delta).

### Tiered payload — right-size hint

``format_hint`` tiers reduce payload on medium paths (``sequence_only`` / ``sequence_plus_pitfalls``).
Full tier (up to ``hint_max_chars``) only when indexed steps > 12.

### Structural gates are insufficient — bad playbooks mislead

Index writes gate on **structure only** (completed, min steps, min input length). A run can
``success=true`` while violating task constraints (e.g. skip required pagination).

On ``books_pagination_stress`` with 120s inter-run pauses:

- Baseline (steering): **5 steps**, ~$0.049, no hint.
- Hinted repeat: **11 steps**, ~$0.122, judge **FAIL** — agent followed a misleading playbook,
  clicked unrelated links, reported false success.

**Root cause:** hint is guidance-only; a low-quality indexed path increases overconfidence and
thrashing, not speed.

**Phase 2 mitigations (not implemented):**

- ``quality_score`` hook on index enqueue (bench judge, verifier, or constraint checks).
- Require evidence of required tool sequence in the compressed window (e.g. sequential pagination).
- Optional mid-run re-hint when ``live_steps > index_steps * 1.25``.

### Bench hygiene — rate limits

Historical runs (the benchmark harness was removed from the repository in 1.0) paused 90 to
120 seconds between phases to avoid OpenAI TPM limits (429s).

## Status

⛔ Disabled in ``build_governor``; implementation removed in 1.0.

✅ Phase 1 design documented above (lookup, inject, background index, ``min_index_steps``, tiered hint).

⏳ Phase 2 deferred: quality gate, constraint-aware indexing, reliable cost savings proof.

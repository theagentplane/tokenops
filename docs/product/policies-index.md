# Policies & actions (index)

This is the single glossary of built-in policy IDs and display labels. Runtime
registration, Store validation, and Admin choices share
[`POLICY_TEMPLATES`](../../src/tokenops/control/config.py). Per-policy behavior
lives under [`docs/policies/`](../policies/).

## Canonical policy IDs

The [default seed](../../src/tokenops/config/default.yaml) contains ten of the eleven
available policies below; `time_budget` is opt-in. Inclusion in the seed does not make
a policy mandatory in custom configurations or change its documented enforcement limitations.

| Policy ID | Display label | Availability | Doc |
|-----------|---------------|--------------|-----|
| `cost_budget` | Cost budget | In default seed | [cost_budget.md](../policies/cost_budget.md) |
| `pre_call_worst_case` | Pre-call worst case | In default seed | [pre_call_worst_case.md](../policies/pre_call_worst_case.md) |
| `step_cap` | Step cap | In default seed | [step_cap.md](../policies/step_cap.md) |
| `time_budget` | Time budget | Opt-in | [time_budget.md](../policies/time_budget.md) |
| `concurrency_cap` | Concurrency cap | In default seed | [concurrency_cap.md](../policies/concurrency_cap.md) |
| `tool_fix` | Tool fix | In default seed | [tool_fix.md](../policies/tool_fix.md) |
| `tool_output_cap` | Tool output cap | In default seed | [tool_output_cap.md](../policies/tool_output_cap.md) |
| `progress_guard` | Progress guard | In default seed | [progress_guard.md](../policies/progress_guard.md) |
| `cost_guard` | Cost guard | In default seed | [cost_guard.md](../policies/cost_guard.md) |
| `context_compaction` | Context compaction | In default seed | [context_compaction.md](../policies/context_compaction.md) |
| `output_runaway` | Output runaway | In default seed | [output_runaway.md](../policies/output_runaway.md) |
| `trajectory_hint` | Trajectory hint | Temporarily disabled | [trajectory_hint.md](../policies/trajectory_hint.md) |

## Naming convention

Use a lowercase **`snake_case` policy ID** everywhere machines identify a built-in
policy. For example:

| Surface | Value for Tool fix |
|---------|--------------------|
| Python module | `tokenops.control.policies.tool_fix` |
| `Detector.name`, `Policy.name`, `Signal.detector` | `tool_fix` |
| YAML key | `governance.policies.tool_fix` |
| Stored `PolicyInstance.template` | `tool_fix` |
| `Action.policy_id`, governance-event `policy`, run `detector` | `tool_fix` |
| Documentation filename / slug | `docs/policies/tool_fix.md` |
| Admin / Dashboard label | `Tool fix (tool_fix)` |

The class symbols `ToolFixDetector` and `ToolFixPolicy` are Python implementation
names, not configuration aliases. Display labels are for people; the UI always
keeps the canonical ID visible and saves the raw ID, not the label.

**Template IDs are not instance IDs.** A `PolicyInstance.id` identifies one saved
configuration and remains user-configurable: `seed_tool_fix`, `pi_...`, and
`research-tools` can all identify instances whose `template` is `tool_fix`.
Seeding still uses `seed_<policy_id>`. Renaming an instance does not rename its
template or detector. Budget IDs such as `run_llm_cap` and action kinds such as
`HALT` are also separate concepts. Existing per-agent selection and
one-effective-instance-per-template behavior are unchanged.

The Governor carries the deciding `Signal.detector` into `Action.policy_id`, so
new governance traces do not infer names from reason text. This optional attribution
does not affect action equality, hashing, or enforcement. Standalone actions
constructed without `policy_id` retain the old best-effort display fallback;
existing event records are not rewritten. Custom detector/policy pairs registered
directly with `Governor.register` keep their own names; the built-in registry does
not restrict that API.

## Compatibility and legacy references

**No supported policy IDs are renamed, and no configuration aliases are added.**
Existing YAML keys, policy class imports, and stored instance IDs remain valid.

- **`tool_freq` was an unsupported catalog typo**, not a legacy runtime alias.
  Use `tool_fix` and `tool_fix.md` in copied references. Config and Store continue
  to reject `tool_freq`, display labels, class names, and instance IDs when used
  as template names; there is no hidden normalization or duplicate registration.
- **`tool_reject` was a stale example/documentation name**, also unsupported by
  the current config and Store registries. The Compose examples now use `tool_fix`
  with their original `registry` and `k` values. Update the key in copied YAML
  without changing its params; for a historical stored row, update only its
  `template`, retaining the instance `id` and params. No runtime alias is added.
- **`trajectory_hint` remains known but temporarily disabled.** It is absent from
  the seed and new Admin choices. Existing stored instances retain their IDs and
  can be disabled in Admin; enabled instances must not enter the effective config.
  `build_governor` rejects any YAML entry with that key, even if its params contain
  `enabled: false`. Remove it from YAML rather than trying another spelling.
  The standalone module remains for research/tests; see its
  [limitations and re-enablement requirements](../policies/trajectory_hint.md).
- Descriptions such as "tool-call validity", the demo chip ID `cost_cap`, and
  historical benchmark scenario names are not additional policy IDs. Use the
  glossary to identify their actual templates rather than mechanically renaming
  scenarios or configuration instances. Demo traces and banners use the same
  canonical policy labels when identity is recorded; legacy records retain their
  existing display fallback.

Any **future** policy rename must specify the old-to-canonical mapping,
deprecation release and removal release, with a warning at the configuration
boundary while the old spelling is supported. Reject configurations containing
both spellings instead of applying a policy twice or silently choosing one.
Migrate stored **template values**, never user-owned instance IDs, and update the
seed, demos, UI labels, glossary, and compatibility tests together. No alias may
be added without this explicit path; none is needed for the corrections above.

## Actions

Actuators (HALT · MUTATE · INJECT · REJECT/QUEUE): see [`docs/control-plane-status.md`](../control-plane-status.md) and [`docs/governance-policy.md`](../governance-policy.md).

[Principles](./principles.md) · [Comparison](./comparison.md) · [Shared ledger](./shared-ledger.md)

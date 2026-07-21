# Completion under budget — shared ledger demo (test agent)

Source: `docs/shared-ledger-comparison.md`

| Mode | Status | Within $0.001 cap | Outcome |
|------|--------|:-----------------:|---------|
| Before (separate ledgers) | completed | No | Run finishes but **over budget** |
| After (shared ledger + policies) | halted | Yes | **pre_call_worst_case** blocks summarize before overspend |

**Slide line:** Without shared governance, the run "succeeds" over cap. With TokenOps, it **stops within budget**.

Compare vs ungoverned overspend (not vs circuit-breaker-only).

# Average cost — shared ledger demo (test agent)

Research + Summarize pipeline, demo mode, **$0.001 run cap** (`prep_ledger_comparison.py`).

Source: `docs/shared-ledger-comparison.md`

| Mode | Research $ | Summarize $ | Total | Within cap? |
|------|----------:|------------:|------:|:-----------:|
| Before (per-process ledger) | $0.0010 | $0.0002 | **$0.0012** | No (completed over cap) |
| After (shared SQLite ledger) | $0.0008 | $0.0000 | **$0.0008** | Yes (halted before overspend) |

**Slide line:** Shared ledger enforces one cap across both agents — **33% lower spend** on this run, stays within budget.

**Note:** Single reproducible demo run, not a multi-trial benchmark. Frame as architecture proof, not production ROI.

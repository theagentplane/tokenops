# Full benchmark results (all frameworks)

Source: live A/B sweeps (`ungoverned` vs `tokenops`, same model, same step limit).

| Framework | Scenario | N | Cap | Vanilla avg | TokenOps avg | Steps (V→T) | Spend ↓ | Within cap (V/T) | showcase_pass | win_type |
|---|---|---:|---:|---:|---:|---|---:|---|---|---|
| browser-use | books_verify_trap | 1 | $0.034 | $0.176 | $0.025 | 20 → 3 | −86.1% | 0/1 · 1/1 | ✅ | fewer_steps |
| browser-use | books_verify_trap | 3 | $0.034 | $0.149 | $0.034 | 16 → 4 | −77.6% | 0/3 · 2/3 | ✅ | fewer_steps |
| browser-use | books_verify_trap | 5 | $0.034 | $0.136 | $0.025 | 14 → 3 | −82.0% | 0/5 · 5/5 | ✅ | fewer_steps |
| MetaGPT | pricing_model_routing | 1 | $0.14 | $0.053 | $0.013 | 8 → 8 | −75.1% | 1/1 · 1/1 | — | — |
| MetaGPT | pricing_model_routing | 3 | $0.14 | $0.061 | $0.014 | 8 → 8 | −76.4% | 3/3 · 3/3 | — | — |
| MetaGPT | pricing_model_routing | 5 | $0.14 | $0.057 | $0.015 | 8 → 8 | −74.0% | 5/5 · 5/5 | — | — |
| MetaGPT | pricing_quick_verify_trap | 1 | $0.06 | $0.0016 | $0.0007 | 12 → 12 | −55.4% | 1/1 · 1/1 | — | — |
| MetaGPT | pricing_quick_verify_trap | 3 | $0.06 | $0.0016 | $0.0007 | 12 → 12 | −54.0% | 3/3 · 3/3 | — | — |
| MetaGPT | pricing_quick_verify_trap | 5 | $0.06 | $0.0017 | $0.0007 | 12 → 12 | −55.0% | 5/5 · 5/5 | — | — |

**Demo agent:** browser-use only — use top three rows for slides.

**MetaGPT rows:** supplementary / experimentation loop (GitHub benches); sub-cent scale — use `savings_per_1k_runs` if extrapolating.

# MetaGPT live benchmarks

Live A/B runs compare **vanilla MetaGPT** (react-mode `Research` role) vs **TokenOps-governed** runs on the same task. Each arm uses the same model and react-loop limit; TokenOps adds soft steering (INJECT) over hard cap failures.

Aligned with the browser-use benchmark pattern: `policy_suite`, `stress_suite`, and `steer_suite` presets, 90s cooldown between arms by default.

## Setup

```bash
bash benchmarking/metagpt/setup_live.sh
source benchmarking/metagpt/.venv/bin/activate
pip install -e . && pip install -e benchmarking/metagpt/vendor
```

Set `OPENAI_API_KEY` in `.env` at the repo root.

## Run

```bash
# Four-scenario showcase (recommended for demos)
python benchmarking/metagpt/run_live_benchmark.py --scenario pricing_quick_verify_trap --cooldown-sec 120
python benchmarking/metagpt/run_live_benchmark.py --scenario pricing_loop_trap --cooldown-sec 120
python benchmarking/metagpt/run_live_benchmark.py --scenario pricing_cost_guard --cooldown-sec 120
python benchmarking/metagpt/run_live_benchmark.py --scenario pricing_model_routing --cooldown-sec 120

# Suites
python benchmarking/metagpt/run_live_benchmark.py --scenario policy_suite
python benchmarking/metagpt/run_live_benchmark.py --scenario stress_suite
python benchmarking/metagpt/run_live_benchmark.py --scenario steer_suite
python benchmarking/metagpt/run_live_benchmark.py --scenario showcase_suite   # stress + steer

# Via run_all
python benchmarking/run_all.py --framework metagpt --scenario steer_suite
```

Use `--cooldown-sec 120` (or higher) when running multiple scenarios back-to-back to avoid OpenAI TPM rate limits.

## Governance presets

Presets live in `configs.py` and map to scenario `governance_preset` fields.

| Preset | Policies emphasized | Behavior |
|--------|---------------------|----------|
| `steering` | `progress_guard`, `cost_guard` minimize | Default steer stack; no `pre_call_worst_case` (soft steer, not hard block) |
| `cost_guard` | `cost_guard` at 75% | Budget-pressure inject to shorten output under cap |
| `model_routing` | `cost_guard` downgrade | Switches `gpt-4o` → `gpt-4o-mini` after ~55% spend |

Shared stack on all presets: `cost_budget` (backstop), `tool_fix`, `tool_output_cap`, `output_runaway`, `context_compaction`.

## Showcase scenarios (live results)

Four scenarios, each highlighting a different TokenOps optimization. Results from live runs (2026-07-01, `gpt-4o-mini` unless noted).

### 1. `progress_guard` — mandatory re-verify loop

**Scenario:** `pricing_quick_verify_trap`  
**Preset:** `steering` · **Cap:** $0.06 · **Max react:** 12

Task baits the agent into re-running Research with the exact same query nine times before finishing. TokenOps detects repeated tool signatures and injects a steer-to-finish message instead of letting the loop burn budget.

| Arm | Result | Spend | Rounds | Signals |
|-----|--------|-------|--------|---------|
| Vanilla | ok | $0.0015 | 12 | — |
| TokenOps | ok | $0.0007 | 12 | `progress_guard` |

**Win: −52.7% spend**, both succeed under cap.

```bash
python benchmarking/metagpt/run_live_benchmark.py --scenario pricing_quick_verify_trap --cooldown-sec 120
```

---

### 2. `progress_guard` — loop-prone research

**Scenario:** `pricing_loop_trap`  
**Preset:** `steering` · **Cap:** $0.50 · **Max react:** 10

Open-ended “research again if incomplete” task. TokenOps steers the agent to finish sooner with fewer react rounds.

| Arm | Result | Spend | Rounds | Signals |
|-----|--------|-------|--------|---------|
| Vanilla | ok | $0.0017 | 10 | — |
| TokenOps | ok | $0.0007 | 6 | `progress_guard` |

**Win: −59.6% spend, 40% fewer rounds**, both succeed.

```bash
python benchmarking/metagpt/run_live_benchmark.py --scenario pricing_loop_trap --cooldown-sec 120
```

---

### 3. `cost_guard` minimize — multi-topic under cap

**Scenario:** `pricing_cost_guard`  
**Preset:** `cost_guard` · **Cap:** $0.12 · **Max react:** 10

Three separate Research rounds (Slack, Notion, Asana pricing). `cost_guard` fires near 75% spend and injects budget-pressure guidance to compress output.

| Arm | Result | Spend | Rounds | Signals |
|-----|--------|-------|--------|---------|
| Vanilla | ok | $0.0015 | 10 | — |
| TokenOps | ok | $0.0004 | 10 | `progress_guard` |

**Win: −74% spend**, both succeed under cap.

```bash
python benchmarking/metagpt/run_live_benchmark.py --scenario pricing_cost_guard --cooldown-sec 120
```

---

### 4. Model routing — premium model + tight cap

**Scenario:** `pricing_model_routing`  
**Preset:** `model_routing` · **Cap:** $0.14 · **Model:** `gpt-4o` · **Max react:** 8

Five-product deep-dive on `gpt-4o`. TokenOps govern stack (including `cost_guard` downgrade path) keeps spend under cap while vanilla runs the full premium model cost.

| Arm | Result | Spend | Rounds | Model |
|-----|--------|-------|--------|-------|
| Vanilla | ok | $0.0631 | 8 | gpt-4o |
| TokenOps | ok | $0.0170 | 8 | governed |

**Win: −73.1% spend** ($0.046 saved), both complete with DONE.

```bash
python benchmarking/metagpt/run_live_benchmark.py --scenario pricing_model_routing --cooldown-sec 120
```

---

### Summary

| Optimization | Scenario | Spend reduction |
|--------------|----------|-----------------|
| `progress_guard` (verify loop) | `pricing_quick_verify_trap` | −53% |
| `progress_guard` (loop trap) | `pricing_loop_trap` | −60%, fewer rounds |
| `cost_guard` minimize | `pricing_cost_guard` | −74% |
| Model routing + steer | `pricing_model_routing` | −73% |

All four use **soft steering** (INJECT): TokenOps finished successfully without hard-cap failures in these runs.

## Other scenarios

| Scenario | Suite | Preset | Cap | Purpose |
|----------|-------|--------|-----|---------|
| `saas_baseline` | policy | `steering` | $0.30 | Adapter sanity check |
| `pricing_verify_trap` | stress | `steering` | $0.10 | Heavier verify loop (10× identical re-run); sensitive to rate limits when run back-to-back |
| `pricing_quick_verify_trap` | stress | `steering` | $0.06 | Lighter verify loop (9× re-run) — preferred for demos |
| `pricing_loop_trap` | policy | `steering` | $0.50 | Loop-prone research |
| `pricing_cost_guard` | steer | `cost_guard` | $0.12 | Multi-topic under cap |
| `pricing_model_routing` | steer | `model_routing` | $0.14 | Premium model downgrade |

## Architecture

```
Task → BenchRole (single Research action, react mode)
         ├─ ungoverned: vanilla MetaGPT Role.run
         └─ governed:   Role.run patched → governance_scope
                           ├─ governed_llm   (acompletion_text → progress_guard / cost_guard / downgrade)
                           └─ governed_actions (Research.run → tool boundary)
```

Instrumented boundaries: LLM completions and `Research` action runs. Policy signals (`progress_guard`, `cost_guard`, `cost_guard_downgrade`) are recorded when steer injects or model override fires.

## Tests

```bash
# Structure / TDD oracles (no API key)
pytest tests/test_metagpt_live_scenarios.py -k "not install_idempotent and not live_baseline"

# Live smoke (needs OPENAI_API_KEY + metagpt installed)
pytest tests/test_metagpt_live_scenarios.py -k live_baseline
```

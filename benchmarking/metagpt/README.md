# MetaGPT live benchmarks

Vanilla **MetaGPT** (react-mode Research role) vs **TokenOps-governed** on the same task.

## Setup

```bash
bash benchmarking/metagpt/setup_live.sh
source benchmarking/metagpt/.venv/bin/activate
pip install -e . && pip install -e benchmarking/metagpt/vendor
```

Set `OPENAI_API_KEY` in `.env`.

## Run

```bash
# Demo tasks
python benchmarking/metagpt/run_live_benchmark.py --scenario showcase_suite --trials 5 --cooldown-sec 120

# Other suites
python benchmarking/metagpt/run_live_benchmark.py --scenario fair_suite
python benchmarking/metagpt/run_live_benchmark.py --scenario trap_suite
python benchmarking/metagpt/run_live_benchmark.py --scenario cap_suite

# Single scenario
python benchmarking/metagpt/run_live_benchmark.py --scenario pricing_quick_verify_trap --trials 5 --cooldown-sec 120 --json
```

Use `--cooldown-sec 120`+ between arms — back-to-back runs often hit TPM limits.

## Config

Most scenarios use **`steering`** (default stack in `configs.py`).

Exception: **`pricing_model_routing`** uses vanilla `gpt-4o` with TokenOps allowed to downgrade to `gpt-4o-mini` (`model_routing` config). That is a setup difference, not a claim that downgrade fires every trial.

We do not expect a specific policy signal on every run. Signals are logged for debugging, not pass/fail.

## Suites

| Suite | Scenarios | Notes |
|-------|-----------|-------|
| `fair_suite` | `saas_baseline`, `pricing_loop_trap` | Normal / soft-loop research |
| `trap_suite` | `pricing_quick_verify_trap`, `pricing_verify_trap` | Same Research query repeated 9–10× |
| `cap_suite` | `pricing_cost_guard`, `pricing_model_routing` | Multi-topic or premium model under cap |
| `showcase_suite` | `pricing_quick_verify_trap`, `pricing_model_routing` | Demo candidates |

### Trap tasks

- `pricing_quick_verify_trap` — re-run Research with the **same query** nine times
- `pricing_verify_trap` — same, ten times (heavier; rate-limit prone — use for stress, not quick demos)

### Dollar scale

Most MetaGPT runs are **sub‑cent**. Good for proving the adapter and steer path work; browser-use is the better framework for headline dollar demos. Use `savings_per_1k_runs_usd` in JSON when reporting MetaGPT deltas.

## Scoring

Browser-use runner has full trial tags and `showcase_pass`. MetaGPT runner reports spend, steps, and optional evaluation oracles — treat **`aspirational_failures`** in evaluation as hints, not requirements that a policy fired.

Full protocol (multi-run sweeps, infra exclusion, aggregation): [../README.md#benchmarking-process](../README.md#benchmarking-process).

For multi-trial comparison:

```bash
python benchmarking/run_trials_sweep.py --framework metagpt --scenario pricing_quick_verify_trap --trial-counts 1,3,5 --cooldown-sec 120
```

## What we claim in a demo

Safe: “On repeated-research traps, governed runs often spend less over N trials.”

Not safe: “`pricing_cost_guard` proves cost_guard” — live runs often fire `progress_guard` first because the agent loops before hitting spend thresholds.

## Architecture

```
Task → BenchRole (Research action, react mode)
         ├─ ungoverned: vanilla Role.run
         └─ governed:   patched Role.run → governance_scope
                           ├─ governed_llm
                           └─ governed_actions
```

## Tests

```bash
pytest tests/test_metagpt_live_scenarios.py -k "not install_idempotent and not live_baseline"
```

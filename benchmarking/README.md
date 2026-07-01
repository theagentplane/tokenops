# TokenOps live benchmarks

Compare **vanilla browser-use** vs **TokenOps-governed** on real tasks.

## Setup

```bash
bash benchmarking/browseruse/setup_live.sh
source benchmarking/browseruse/.venv/bin/activate
```

Set `OPENAI_API_KEY` or `BROWSER_USE_API_KEY` in `.env`.

## Run

```bash
# Policy-focused suite (example.com tight cap + books loop trap)
python benchmarking/run_all.py --scenario policy_suite

# Stress suite (loop traps under tight caps — vanilla overspend vs TokenOps governance)
python benchmarking/run_all.py --scenario stress_suite

# Cost showcase — four scenarios, each a different TokenOps cost strategy (see browseruse/README.md)
python benchmarking/run_all.py --scenario cost_showcase_suite --cooldown-sec 60

# Single scenario
python benchmarking/browseruse/run_live_benchmark.py --scenario books_verify_trap
python benchmarking/browseruse/run_live_benchmark.py --scenario books_loop_trap --mode-only tokenops
```

See **[benchmarking/browseruse/README.md](browseruse/README.md)** for setup, governance presets, and the cost showcase scenarios with live results.

Scenarios:
- `example_tight_cap` ($0.30 / 12 steps), `books_loop_trap` ($0.50 / 20 steps) — policy suite
- `books_verify_trap` ($0.034 / 20 steps) — reload loop bait; vanilla often overspends on mandatory re-checks while TokenOps `progress_guard` INJECT + `cost_budget` cap spend
- `example_verify_trap` ($0.018 / 15 steps) — nine reload cycles on example.com

**Cost showcase suite** (`cost_showcase_suite`):

| Scenario | Optimization | Cap | Live win (spend) |
|----------|--------------|-----|------------------|
| `example_verify_trap` | `progress_guard` | $0.018 | −65% |
| `books_verify_trap` | `progress_guard` + `cost_budget` | $0.034 | −73%, within cap |
| `books_cost_guard` | `cost_guard` minimize | $0.052 | −16% to −49% |
| `books_pagination_stress` | `cost_budget` | $0.10 | −74%, vanilla fails |

Default suite runs vanilla first, 90s cooldown, then TokenOps per scenario.

## MetaGPT live runs

See **[benchmarking/metagpt/README.md](metagpt/README.md)** for setup, showcase scenarios, live results, and governance presets.

```bash
bash benchmarking/metagpt/setup_live.sh
source benchmarking/metagpt/.venv/bin/activate
pip install -e . && pip install -e benchmarking/metagpt/vendor
```

```bash
# Four-scenario showcase (one optimization each)
python benchmarking/metagpt/run_live_benchmark.py --scenario pricing_quick_verify_trap --cooldown-sec 120
python benchmarking/metagpt/run_live_benchmark.py --scenario pricing_loop_trap --cooldown-sec 120
python benchmarking/metagpt/run_live_benchmark.py --scenario pricing_cost_guard --cooldown-sec 120
python benchmarking/metagpt/run_live_benchmark.py --scenario pricing_model_routing --cooldown-sec 120

# Suites
python benchmarking/metagpt/run_live_benchmark.py --scenario policy_suite
python benchmarking/metagpt/run_live_benchmark.py --scenario showcase_suite
python benchmarking/run_all.py --framework metagpt --scenario steer_suite
```

| Scenario | Optimization | Cap | Live win (spend) |
|----------|--------------|-----|------------------|
| `pricing_quick_verify_trap` | `progress_guard` | $0.06 | −53% |
| `pricing_loop_trap` | `progress_guard` | $0.50 | −60%, fewer rounds |
| `pricing_cost_guard` | `cost_guard` minimize | $0.12 | −74% |
| `pricing_model_routing` | model routing (`gpt-4o`) | $0.14 | −73% |

TDD (no API key): `pytest tests/test_metagpt_live_scenarios.py -k "not install_idempotent and not live_baseline"`

Live smoke: `pytest tests/test_metagpt_live_scenarios.py -k live_baseline`

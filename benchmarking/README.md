# TokenOps live benchmarks

Side-by-side runs: **vanilla agent** vs **TokenOps-governed** on the same task, same model, same step limit.

## What this proves (and does not)

**Proves:** On loop-prone or cap-tight tasks, TokenOps often spends less than vanilla.

**Does not prove:** That a specific policy fires every run, that every scenario is a clean win, or that production ROI is guaranteed. LLM agents are non-deterministic — we score outcomes, not “policy X must fire on trial 3.”

## Setup

**Browser-use**

```bash
bash benchmarking/browseruse/setup_live.sh
source benchmarking/browseruse/.venv/bin/activate
```

**MetaGPT**

```bash
bash benchmarking/metagpt/setup_live.sh
source benchmarking/metagpt/.venv/bin/activate
pip install -e . && pip install -e benchmarking/metagpt/vendor
```

Set `OPENAI_API_KEY` (or `BROWSER_USE_API_KEY` for browser-use) in `.env`.

## Suites

Both frameworks use the same idea:

| Suite | Purpose | What “good” looks like |
|-------|---------|------------------------|
| `fair_suite` | Normal tasks | TokenOps ≈ vanilla (no big regression) |
| `trap_suite` | Forced wasteful repeats (reload / re-research) | TokenOps usually cheaper |
| `cap_suite` | Long job + tight budget | TokenOps stays under cap more often |
| `showcase_suite` | Hand-picked demo tasks | Cheaper **and** success within budget (`showcase_pass`) |

Old names still work: `policy_suite` → `fair_suite`, `stress_suite` → `trap_suite`, `steer_suite` → `cap_suite`, `cost_showcase_suite` → `showcase_suite`.

## Run

```bash
# Browser-use showcase (2 scenarios)
python benchmarking/browseruse/run_live_benchmark.py --scenario showcase_suite --trials 5 --cooldown-sec 60

# MetaGPT showcase
python benchmarking/metagpt/run_live_benchmark.py --scenario showcase_suite --trials 5 --cooldown-sec 120

# Single scenario
python benchmarking/browseruse/run_live_benchmark.py --scenario books_verify_trap --trials 1 --json

# Both frameworks
python benchmarking/run_all.py --scenario showcase_suite --cooldown-sec 60
```

**Multi-trial sweep** (default N=1,3,5):

```bash
python benchmarking/run_trials_sweep.py --suite showcase_suite --framework both --cooldown-sec 60
```

Use `--cooldown-sec 60`–`120` between arms to reduce rate limits. Vanilla runs first, then TokenOps.

## Scoring (browser-use)

Each trial is tagged: `ok`, `infra` (rate limit / empty run — dropped from averages), `halted`, `failed`.

JSON output includes:

- `spend_reduction_pct`, `delta_usd_per_trial`, `savings_per_1k_runs_usd`
- `win_type`: `fewer_steps`, `cheaper_steps`, `outcome`, `mixed`, `none`
- `showcase_pass`: TokenOps cheaper **and** at least as good on success-within-budget

We do **not** require a named policy to fire on every trial.

## Framework docs

- [browseruse/README.md](browseruse/README.md) — browser tasks, suites, scoring
- [metagpt/README.md](metagpt/README.md) — MetaGPT adapter, suites

## Tests (no API key)

```bash
pytest tests/test_trial_status.py tests/test_browseruse_suites.py \
  tests/test_metagpt_live_scenarios.py -k "not install_idempotent and not live_baseline"
```

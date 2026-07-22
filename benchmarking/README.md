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

## Benchmarking process

How we run, score, and report live A/B results. Same protocol for browser-use and MetaGPT unless noted.

### 1. One A/B pair (single trial)

Each **trial** is one full task attempt on **both arms** with the same scenario, model, and step/react limit:

1. **Ungoverned (vanilla)** — agent with no TokenOps wiring
2. Cooldown (`--cooldown-sec`, default 60–120s) — reduces OpenAI TPM / 429 errors
3. **TokenOps** — same task, governance stack enabled

Run a single pair:

```bash
python benchmarking/browseruse/run_live_benchmark.py --scenario books_verify_trap --trials 1
```

Add `--json` for machine-readable output. Use `--mode-only ungoverned` or `tokenops` to re-run one arm.

### 2. Multi-trial runs (same scenario, N repeats)

Pass `--trials N` to repeat the full A/B pair N times. Each repeat is an independent agent run (non-deterministic LLM + browser timing).

```bash
python benchmarking/browseruse/run_live_benchmark.py --scenario books_verify_trap --trials 5 --cooldown-sec 90
```

**Why multiple trials:** One run can hit rate limits, flake, or get lucky. We report **averages over scored trials**, not cherry-picked single runs.

**Parallel trials (optional):** `--parallel-batch K` runs up to K trials concurrently inside one subprocess. Default is sequential (`1`). On a laptop, keep `--parallel-batch 1` and `--jobs 1` in sweeps — parallel runs worsen 429s.

### 3. Trial-count sweep (N=1, 3, 5 across scenarios)

`run_trials_sweep.py` orchestrates many subprocess runs and writes one JSON table:

```bash
python benchmarking/run_trials_sweep.py \
  --suite showcase_suite \
  --framework both \
  --trial-counts 1,3,5 \
  --cooldown-sec 90 \
  --jobs 1 \
  --parallel-batch 1 \
  --out /tmp/showcase_sweep.json
```

| Flag | Role |
|------|------|
| `--suite showcase_suite` | All demo scenarios per framework (see below) |
| `--scenario <id>` | Single scenario instead of suite |
| `--trial-counts 1,3,5` | Run separate jobs at each N (default) |
| `--out path.json` | Append results; **resume** skips completed `(framework, scenario, trials)` keys |
| `--jobs N` | Concurrent subprocesses for **N≥5 jobs only** (default 2) |
| `--parallel-batch N` | Trial concurrency inside each N≥5 run (default 3; use 1 locally) |

**Scheduling order:** N=1 first (sequential), then N=2–4 (sequential), then N≥5 (optional parallel subprocesses). This avoids silently skipping mid-N counts.

**Showcase scenarios by framework:**

| Framework | Scenarios in `showcase_suite` sweep |
|-----------|-------------------------------------|
| browser-use | `books_verify_trap` |
| MetaGPT | `pricing_quick_verify_trap`, `pricing_model_routing` |

### 4. Trial tags (what counts in averages)

Every trial is classified before aggregation (`benchmarking/common/trial.py`):

| Tag | Meaning | Included in averages? |
|-----|---------|------------------------|
| `ok` | Completed run with spend/steps | **Yes** |
| `infra` | Rate limit (429), empty run ($0, 0 steps), or similar transport failure | **No — dropped** |
| `halted` | TokenOps halted the run (budget/policy stop) | Yes (counted; may affect success rate) |
| `failed` | Agent did not finish the task | Yes |

**Infra failures are ignored for spend/step averages** so a bad API day does not skew the comparison. The summary still reports `scored_trials` vs `total_trials` and `infra_trials` dropped per arm:

```
scored: 4/5  infra dropped: 1
avg spend: $0.0246  (computed over 4 scored trials only)
```

Browser-use surfaces this in CLI and JSON (`scored_trials`, `infra_trials`). MetaGPT uses the same trial runner patterns where wired; evaluation oracles are separate (below).

### 5. Aggregated metrics (per scenario × N)

After N trials, each arm gets:

| Field | Meaning |
|-------|---------|
| `avg_spend_usd` / `median_spend_usd` | Mean/median over **scored** trials only |
| `avg_steps` | Mean boundary steps (browser) or react rounds (MetaGPT) |
| `successes` | Task finished successfully (scored trials) |
| `success_within_budget` | Finished **and** spend ≤ scenario cap |

Cross-arm comparison adds:

| Field | Meaning |
|-------|---------|
| `spend_reduction_pct` | `(vanilla_avg − tokenops_avg) / vanilla_avg × 100` |
| `delta_usd_per_trial` | Absolute $ saved per scored trial |
| `savings_per_1k_runs_usd` | `delta × 1000` — useful for slide-scale extrapolation |
| `win_type` | How TokenOps won: `fewer_steps`, `cheaper_steps`, `outcome`, `mixed`, `none` |
| `showcase_pass` | TokenOps **cheaper** and **≥ vanilla** on success-within-budget (browser-use) |

**`showcase_pass`** is the demo-safe bar for showcase scenarios: cheaper spend **and** at least as many cap-compliant successes as vanilla. Use rows where this is `true` for slides.

**`win_type` rules (simplified):**

- `fewer_steps` — spend down **and** steps down ≥10%
- `cheaper_steps` — spend down, steps similar
- `outcome` — more successes within cap, spend not better
- `mixed` — spend and outcome both improved
- `none` — no clear TokenOps win on these axes

### 6. What we do **not** score as pass/fail

- **Named policy signals** (`progress_guard`, `cost_guard_downgrade`, …) — logged for debugging only
- MetaGPT **`aspirational_failures`** in evaluation — hints (e.g. “expected downgrade signal”), not structural failures
- **Preset-as-demo** — we do not claim “scenario X proves policy Y fired on trial 3”

LLM agents are stochastic. We score **outcomes and spend over N trials**, not deterministic policy choreography.

### 7. Recommended workflow (demo prep)

1. **Smoke:** `--trials 1` on one scenario per framework
2. **Stability:** `--trials 5` or sweep `--trial-counts 1,3,5` with `--cooldown-sec 90+`
3. **Report:** Use sweep JSON + terminal table; cite N=5 rows for camera, N=1 for quick sanity
4. **Filter:** Prefer `showcase_pass: true`; disclose `infra_trials` if any were dropped
5. **Honest framing:** “Often / in N trials / on average” — not “always”

Example full showcase sweep (local-friendly, ~80 min):

```bash
python benchmarking/run_trials_sweep.py \
  --suite showcase_suite --framework both \
  --trial-counts 1,3,5 --cooldown-sec 90 \
  --jobs 1 --parallel-batch 1 \
  --out /tmp/showcase_sweep.json
```

### 8. Framework differences

| | browser-use | MetaGPT |
|---|-------------|---------|
| Trial tags + infra drop | Full | Partial (spend/steps; see runner JSON) |
| `showcase_pass` | In JSON + sweep table | Evaluation oracles; spend wins in JSON |
| Dollar scale | Cents–dollars per run | Sub-cent typical |
| Best demo | `books_verify_trap` (reload loop) | `pricing_quick_verify_trap` (research loop) |
| Cooldown | 60–90s | 120s+ (TPM-sensitive) |

## Scoring reference (browser-use)

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

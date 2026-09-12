# Testing the TokenOps control plane

How to run the tests yourself, what each suite proves, and how to add a test when you add a
policy. Default CI runs **everything that needs no real API key or vendored framework** —
including the example-bench end-to-end tests (real servers, real Governor, real policy
HALT/MUTATE decisions; only the model call and search tool are faked, so no network or key
is needed). Only `live` (genuinely needs an API key / vendored framework) is excluded.

---

## Run everything (default CI)

From the repo root:

```bash
python -m pytest -q
```

Pytest config lives in `pyproject.toml` (`testpaths=["tests"]`, `pythonpath=["src", "."]`,
`addopts = "-m 'not live'"`). Only the `live` suite is excluded by default; `e2e` is part of
the regular run precisely so a real run+policy regression can't go unnoticed the way #127
did (two example-bench e2e tests silently broke against `main` for a while because they
were excluded from CI at the time).

Useful variants:

```bash
python -m pytest -q tests/test_cost_budget.py      # one policy
python -m pytest -q -k "halt or budget"            # by keyword
python -m pytest -q -m e2e                         # only the example benches
python -m pytest -q -m live                        # needs keys / vendored frameworks
python -m pytest -v                                # show every test name
python -m pytest -x                                # stop at first failure
```

## What the suites cover

| File | Proves |
|------|--------|
| `test_ledger.py` | pricing, single-source `cum_spent`, velocity/recent, `budget_left`, inflight, sticky halt |
| `test_cost_budget.py` … `test_tool_fix.py` (+ `test_trajectory_hint.py`) | one per policy — detector + Action (`FakeView`) |
| `test_policies_wrap_integration.py` | **all** policies through Governor + mocked `wrap_complete` / observe |
| `test_config.py` | `build_governor` wires policies from a dict |
| `test_integration.py` | in-process wrap + fake model halt |
| `test_apply.py` | corrective controls through `wrap_complete` |
| `test_store.py` | SQLite CRUD, auto-seed, clear/reseed |
| `test_attribution.py` | registration, headers, fail-closed resolve |
| `test_boundary.py` / `test_chronicle_boundary.py` | `@boundary` + Chronicle ingest |
| `test_attribution_ledger_policies_e2e.py` | register → ledger → HALT (in-process + HTTP) |
| `test_cross_process_budget_gating.py` | shared SQLite spend/halt across Governors |
| `test_server_enforcement.py` | Admin store → server → HALT → RunRecord |
| `tests/examples/` | real A2A bench / triad servers, real Governor + policy HALT/MUTATE, real multi-agent shared ledger (marker: `e2e`, no key needed, **now in the default run**) |
| `tests/benchmarking/` | harness unit tests; MetaGPT/browser-use need vendor (marker: `live` where applicable) |

## How the tests stay isolated

Two helpers in `tests/conftest.py`:

* **`FakeView`** — a `LedgerView` whose reads are fixed by constructor kwargs
* **`CollectingControls`** — OUT connector that records Actions (and raises on HALT)
* **`toy_price`** — deterministic price book
* **`TOKENOPS_SKIP_GOVERNANCE_SEED=1`** — set in `tests/conftest.py` so fixtures get an empty store unless they seed explicitly

## DB scripts (governance reset)

```bash
make db-clear      # delete all rows (runs + governance)
make db-reseed     # replace governance from default.yaml
make db-reset      # clear + reseed
```

## Example e2e (offline, mocked LLM — part of the default run)

```bash
pip install -e ".[dev,examples]"
python -m pytest -q -m e2e   # just this slice, e.g. while iterating on it
```

# Testing the TokenOps control plane

How to run the tests yourself, what each suite proves, and how to add a test when you add a
policy. Default CI runs **offline core tests only** (no API keys).

---

## Run everything (default CI)

From the repo root:

```bash
python -m pytest -q
```

Pytest config lives in `pyproject.toml` (`testpaths=["tests"]`, `pythonpath=["src", "."]`,
`addopts = "-m 'not e2e and not live'"`). Example / live suites are excluded by default.

Useful variants:

```bash
python -m pytest -q tests/test_cost_budget.py      # one policy
python -m pytest -q -k "halt or budget"            # by keyword
python -m pytest -q -m e2e                         # example benches (mocked LLM)
python -m pytest -q -m live                        # needs keys / vendored frameworks
python -m pytest -v                                # show every test name
python -m pytest -x                                # stop at first failure
```

## What the suites cover

| File | Proves |
|------|--------|
| `test_ledger.py` | pricing, single-source `cum_spent`, velocity/recent, `budget_left`, inflight, sticky halt |
| `test_cost_budget.py` … `test_output_runaway.py` | one per policy — detector + Action |
| `test_config.py` | `build_governor` wires policies from a dict |
| `test_integration.py` | in-process wrap + fake model halt |
| `test_apply.py` | corrective controls through `wrap_complete` |
| `test_store.py` | SQLite CRUD, auto-seed, clear/reseed |
| `test_attribution.py` | registration, headers, fail-closed resolve |
| `test_boundary.py` / `test_chronicle_boundary.py` | `@boundary` + Chronicle ingest |
| `test_attribution_ledger_policies_e2e.py` | register → ledger → HALT (in-process + HTTP) |
| `test_cross_process_budget_gating.py` | shared SQLite spend/halt across Governors |
| `test_server_enforcement.py` | Admin store → server → HALT → RunRecord |
| `tests/examples/` | A2A bench / triad e2e (marker: `e2e`) |
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

## Example e2e (offline, mocked LLM)

```bash
pip install -e ".[dev,examples]"
python -m pytest -q -m e2e
```

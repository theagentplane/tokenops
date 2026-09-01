# Contributing to TokenOps

Thanks for helping improve TokenOps. This repo publishes the PyPI package
`agent-tokenops` (import name `tokenops`) plus runnable examples and benchmarks.

By participating, you agree to follow our [Code of Conduct](CODE_OF_CONDUCT.md).

## Setup

Requires Python 3.10+.

```bash
git clone https://github.com/theagentplane/tokenops.git
cd tokenops
make install          # pip install -e ".[dev,examples]"
cp .env.example .env  # optional API keys for live demos
```

Install [Git LFS](https://git-lfs.com) if you need local copies of demo videos /
the product deck (tracked as LFS pointers).

Optional local hooks (same checks as CI: ruff + mypy):

```bash
pre-commit install
```

## Development loop

```bash
make lint     # ruff check + format --check + mypy
make format   # ruff format (auto-fix)
make test     # pytest (skips e2e/live by default)
```

Or run tools directly:

```bash
ruff check src tests examples
ruff format --check src tests examples
mypy src/tokenops
python -m pytest -q
```

Markers (see `docs/testing.md`):

- default CI: excludes `e2e` and `live`
- `pytest -m e2e` for example end-to-end suites
- `pytest -m live` when API keys / vendored frameworks are available

## Where to change things

| Area | Path |
|------|------|
| Library / control plane SDK | `src/tokenops/` |
| Unit + integration tests | `tests/` |
| Demo agents / orchestrators | `examples/` |
| Field guide | `docs/guides/field-guide-add-tokenops.md` |
| Governance policy docs | `docs/policies/` |

Keep agent business logic in `examples/` (or your app); the library owns
governance wraps, ledger, and the control-plane server.

## Pull requests

**Open an issue first.** For anything beyond a typo or a small docs fix, file an
issue describing the problem or the feature, and wait for a maintainer to agree
on the approach before you write the patch. It keeps you from spending a weekend
on a change we cannot merge, and it gives the PR something to close.

1. Open an issue and get agreement on the approach.
2. Branch, then keep the PR focused (one concern per change).
3. Add or update tests when behavior changes.
4. Run `make lint` and `make test` before opening the PR.
5. Update `CHANGELOG.md` for user-visible changes (see `RELEASING.md`).
6. Link the issue in the PR description (`Fixes #123`).

Typos, broken links, and formatting fixes can skip step 1 and go straight to a
pull request.

## Discussions vs issues

Use **[GitHub Discussions](https://github.com/theagentplane/tokenops/discussions)** for conversation:

| Category | Use for |
|----------|---------|
| Q&A | Integration help (`tokenops_run`, `wrap_complete`, `TOKENOPS_URL`, policies) |
| Ideas | Feature sketches and RFCs |
| Show and tell | Integrations, benches, production setups |
| General | Everything else |

Use **Issues** for work that needs a patch:

- Bug reports: expected vs actual behavior, minimal repro, versions.
- Concrete, ready-to-implement features (problem statement first; link related docs).
- The issue comes before the pull request, so the approach can be agreed there.
- Security: see [SECURITY.md](SECURITY.md); do not file public issues or discussions for vulns.

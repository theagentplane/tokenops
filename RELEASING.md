# Releasing

TokenOps publishes to PyPI as **`agent-tokenops`** (import: `tokenops`) using
GitHub Actions with **Trusted Publishing (OIDC)** — no API tokens are stored
anywhere. Same pattern as Chronicle (`agent-chronicle` → `import chronicle`).

One workflow run is atomic: **verify → build → git tag → GitHub Release → PyPI**.

## One-time setup (Trusted Publishing)

### 1. Pending publisher on PyPI

1. Sign in at [pypi.org](https://pypi.org) (account that will own the project).
2. Open [Publishing](https://pypi.org/manage/account/publishing/)
   (*Your account* → *Publishing*).
3. Under **Add a new pending publisher**, choose **GitHub** and fill in:
   - PyPI project name: `agent-tokenops`
   - Owner: `theagentplane`
   - Repository: `tokenops`
   - Workflow filename: `release.yml`
   - Environment name: `pypi`
4. Save. The project does **not** exist yet; the first successful CI upload
   creates it and binds that publisher permanently.

Optional: do the same on [TestPyPI](https://test.pypi.org/manage/account/publishing/)
for a dry run (same project name `agent-tokenops`).

### 2. GitHub Environment

In the `theagentplane/tokenops` repo:

1. **Settings → Environments → New environment**
2. Name it exactly `pypi` (must match `environment: pypi` in `release.yml` and
   the PyPI publisher form).
3. Optional: add required reviewers so a human must approve before upload.

No secrets needed — OIDC uses `permissions: id-token: write` in `release.yml`.

### 3. Optional TestPyPI dry run

```bash
make dist
twine upload --repository testpypi dist/*
pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ agent-tokenops
```

## Cutting a release

1. Move the `CHANGELOG.md` `[Unreleased]` items under a new version heading with
   today's date; start a fresh empty `[Unreleased]`.
2. Bump `version` in `pyproject.toml` **and** `__version__` in
   `src/tokenops/__init__.py` following SemVer. Commit and merge to `main`.
3. In GitHub: **Actions → Release → Run workflow**
   - Branch: `main` (the commit that has the version bump)
   - Tag (optional): e.g. `v0.1.0` — leave empty to use `v{version}` from
     `pyproject.toml`
4. The workflow will, in one run:
   1. Require the tag to match `pyproject.toml` version
   2. Build sdist/wheel and `twine check`
   3. Create and push the git tag
   4. Create the GitHub Release (attaches dist artifacts)
   5. Upload to PyPI (may wait on `pypi` environment approval)
5. Verify:
   ```bash
   pip install agent-tokenops==X.Y.Z
   python -c "import tokenops; print(tokenops.__version__)"
   ```

## Version matching (why the workflow checks)

PyPI versions are **immutable** and come from metadata inside the built wheel —
that metadata is read from `pyproject.toml` at build time. The git tag
(`v0.1.0`) is only a label; it does **not** set the package version.

If you passed tag `v0.1.1` but `pyproject.toml` still says `0.1.0`, the workflow
refuses to continue. Empty tag input defaults to `v` + the pyproject version.

Also keep `tokenops.__version__` in sync so runtime version matches pip.

## Versioning notes

- Stay in `0.x` while the control-plane / SDK surface may still change.
- Install name: `agent-tokenops`. Import name: `tokenops`.
- Do not create tags or GitHub Releases by hand for normal cuts — use
  **Run workflow** so tag, Release, and PyPI stay in lockstep.

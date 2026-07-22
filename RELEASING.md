# Releasing

TokenOps publishes to PyPI as **`agent-tokenops`** (import: `tokenops`) using
GitHub Actions with **Trusted Publishing (OIDC)** — no API tokens are stored
anywhere. Same pattern as Chronicle (`agent-chronicle` → `import chronicle`).

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
   `src/tokenops/__init__.py` following SemVer.
3. Commit and tag:
   ```bash
   git commit -am "Release vX.Y.Z"
   git tag vX.Y.Z
   git push && git push --tags
   ```
4. Create a **GitHub Release** from the tag. Publishing the release triggers
   `release.yml`, which builds and uploads to PyPI automatically.
5. Verify:
   ```bash
   pip install agent-tokenops==X.Y.Z
   python -c "import tokenops; print(tokenops.__version__)"
   ```

## Version matching (why the workflow checks)

PyPI versions are **immutable** and come from metadata inside the built wheel —
that metadata is read from `pyproject.toml` at build time. The git tag
(`v0.1.0`) is only a label on GitHub; it does **not** set the package version.

If you tagged `v0.1.1` but forgot to bump `pyproject.toml` (still `0.1.0`), CI
would try to upload **0.1.0** again while the Release page says 0.1.1. The
workflow strips the leading `v` from the Release tag and requires it to equal
`version` in `pyproject.toml` before upload.

Also keep `tokenops.__version__` in sync so runtime version matches pip.

## Versioning notes

- Stay in `0.x` while the control-plane / SDK surface may still change.
- Install name: `agent-tokenops`. Import name: `tokenops`.

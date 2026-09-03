"""The README front door must keep working.

``python -m tokenops.demo`` is the first thing a new user runs. It lives inside
the package on purpose: ``examples/`` is not shipped in the wheel, so anything
under it cannot be run by someone who only did ``pip install agent-tokenops``.
If the public surface the demo uses ever changes, this fails before the README
goes stale.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEMO = REPO_ROOT / "src" / "tokenops" / "demo.py"


def test_demo_shows_the_governed_run_halting(tmp_path):
    """It runs standalone, spends, and stops itself. No API keys, no server."""
    env = dict(os.environ)
    # A user's shell has neither of these. conftest sets SKIP_GOVERNANCE_SEED for
    # the suite, and inheriting it seeds no policies at all, so nothing enforces.
    env.pop("TOKENOPS_URL", None)
    env.pop("TOKENOPS_SKIP_GOVERNANCE_SEED", None)
    env.update(
        {
            "TOKENOPS_EMBEDDED": "1",
            "TOKENOPS_DB": str(tmp_path / "demo.db"),
            # Pin the seed the README quotes. The suite and the Makefile both set
            # TOKENOPS_CONFIG, and inheriting either changes the budget under test.
            "TOKENOPS_CONFIG": str(REPO_ROOT / "src" / "tokenops" / "config" / "default.yaml"),
            # cp1252 is the default Windows console encoding; a non-ASCII byte in
            # any halt reason on this path would raise UnicodeEncodeError here.
            "PYTHONIOENCODING": "cp1252",
        }
    )
    proc = subprocess.run(
        [sys.executable, "-m", "tokenops.demo"],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=REPO_ROOT,
        env=env,
    )

    assert proc.returncode == 0, proc.stderr
    assert "without TokenOps" in proc.stdout
    assert "with TokenOps" in proc.stdout
    assert "halted at call" in proc.stdout
    assert "budget 'run_llm_cap' exhausted" in proc.stdout


def test_demo_uses_only_public_api():
    """Guard the snippet the README inlines: these imports are the contract."""
    source = DEMO.read_text(encoding="utf-8")
    for expected in (
        "from tokenops import ControlPlaneClient, tokenops_run",
        "from tokenops.control import Halt, wrap_complete",
        "from tokenops.providers.types import ModelResponse",
    ):
        assert expected in source, f"demo no longer imports: {expected}"


def test_demo_ships_inside_the_wheel():
    """The whole reason it moved out of examples/.

    setuptools packages only ``src/tokenops*``, so anything under ``examples/`` is
    absent after ``pip install agent-tokenops``. A README that tells a new user to
    run a file they do not have is worse than no README, so keep the demo importable
    as a module rather than reachable only from a clone.
    """
    assert DEMO.parent == REPO_ROOT / "src" / "tokenops", "demo must live in the package"

    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'where = ["src"]' in pyproject
    assert 'include = ["tokenops*"]' in pyproject

    # And it must actually be runnable as one.
    proc = subprocess.run(
        [sys.executable, "-c", "import tokenops.demo; print(tokenops.demo.main)"],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=REPO_ROOT,
    )
    assert proc.returncode == 0, proc.stderr

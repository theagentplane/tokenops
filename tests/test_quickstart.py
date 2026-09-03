"""The README front door must keep working.

``examples/quickstart.py`` is the first thing a new user runs and the snippet the
README shows inline. If the public surface it uses ever changes, this fails
before the README goes stale.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
QUICKSTART = REPO_ROOT / "examples" / "quickstart.py"


def test_quickstart_halts_on_the_run_budget(tmp_path):
    """It runs standalone, spends, and stops itself. No API keys, no server."""
    env = dict(os.environ)
    # A user's shell has neither of these. conftest sets SKIP_GOVERNANCE_SEED for
    # the suite, and inheriting it seeds no policies at all, so nothing enforces.
    env.pop("TOKENOPS_URL", None)
    env.pop("TOKENOPS_SKIP_GOVERNANCE_SEED", None)
    env.update(
        {
            "TOKENOPS_EMBEDDED": "1",
            "TOKENOPS_DB": str(tmp_path / "quickstart.db"),
            # Pin the seed the README quotes. The suite and the Makefile both set
            # TOKENOPS_CONFIG, and inheriting either changes the budget under test.
            "TOKENOPS_CONFIG": str(REPO_ROOT / "src" / "tokenops" / "config" / "default.yaml"),
            # cp1252 is the default Windows console encoding; a non-ASCII byte in
            # any halt reason on this path would raise UnicodeEncodeError here.
            "PYTHONIOENCODING": "cp1252",
        }
    )
    proc = subprocess.run(
        [sys.executable, str(QUICKSTART)],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=REPO_ROOT,
        env=env,
    )

    assert proc.returncode == 0, proc.stderr
    assert "HALTED" in proc.stdout
    assert "budget 'run_llm_cap' exhausted" in proc.stdout


def test_quickstart_uses_only_public_api():
    """Guard the snippet the README inlines: these imports are the contract."""
    source = QUICKSTART.read_text(encoding="utf-8")
    for expected in (
        "from tokenops import ControlPlaneClient, tokenops_run",
        "from tokenops.control import Halt, wrap_complete",
        "from tokenops.providers.types import ModelResponse",
    ):
        assert expected in source, f"quickstart no longer imports: {expected}"

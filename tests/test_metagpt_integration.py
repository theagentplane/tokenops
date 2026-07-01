"""Tests for MetaGPT TokenOps adapter."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

VENDOR_ROOT = Path(__file__).resolve().parents[1] / "benchmarking/metagpt/vendor"
METAGPT_OK = (VENDOR_ROOT / "metagpt").exists() and importlib.util.find_spec("metagpt") is not None

pytestmark = pytest.mark.skipif(not METAGPT_OK, reason="pip install -e benchmarking/metagpt/vendor")


def test_install_idempotent():
    from benchmarking.metagpt.integration import install, uninstall

    install()
    install()
    uninstall()

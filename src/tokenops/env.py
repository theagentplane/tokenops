from __future__ import annotations

from pathlib import Path

_LOADED = False


def load_env() -> None:
    """Load .env from the repo root (applies to all agent processes)."""
    global _LOADED
    if _LOADED:
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        _LOADED = True
        return

    repo_root = Path(__file__).resolve().parents[2]
    load_dotenv(repo_root / ".env")
    load_dotenv()  # fallback: .env in current working directory
    _LOADED = True

"""``python -m tokenops.server`` — run the control plane (default port 7700)."""

from __future__ import annotations

import os

import uvicorn

from tokenops.env import load_env


def main() -> None:
    load_env()
    host = os.environ.get("TOKENOPS_HOST", "0.0.0.0")
    port = int(os.environ.get("TOKENOPS_PORT", "7700"))
    uvicorn.run(
        "tokenops.server.app:create_app",
        factory=True,
        host=host,
        port=port,
        log_level=os.environ.get("TOKENOPS_LOG_LEVEL", "info"),
    )


if __name__ == "__main__":
    main()

from __future__ import annotations

import os
import sys

from tokenops.env import load_env
from examples.app_config import load_config

load_env()


def main() -> None:
    cfg = load_config().research
    os.environ.setdefault("TOKENOPS_CONFIG", os.environ.get("TOKENOPS_CONFIG", ""))
    if cfg.framework == "langchain":
        from examples.agents.research.langchain.server import main as run

        run()
    else:
        from examples.agents.research.native.server import main as run

        run()


if __name__ == "__main__":
    main()

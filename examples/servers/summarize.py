from __future__ import annotations

from examples.app_config import load_config
from tokenops.env import load_env

load_env()


def main() -> None:
    cfg = load_config().summarize
    if cfg.framework == "langchain":
        from examples.agents.summarize.langchain.server import main as run

        run()
    else:
        from examples.agents.summarize.native.server import main as run

        run()


if __name__ == "__main__":
    main()

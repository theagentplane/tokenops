from __future__ import annotations

from tokenops.env import load_env

load_env()


def main() -> None:
    from bench.triad.planner.server import main as run

    run()


if __name__ == "__main__":
    main()

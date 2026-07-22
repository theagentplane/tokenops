"""Thin entrypoint: python -m examples.servers.scout"""


def main() -> None:
    from examples.brief.scout.server import main as run

    run()


if __name__ == "__main__":
    main()

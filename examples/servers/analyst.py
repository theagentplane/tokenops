"""Thin entrypoint: python -m examples.servers.analyst"""


def main() -> None:
    from examples.brief.analyst.server import main as run

    run()


if __name__ == "__main__":
    main()

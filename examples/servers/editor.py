"""Thin entrypoint: python -m examples.servers.editor"""


def main() -> None:
    from examples.brief.editor.server import main as run

    run()


if __name__ == "__main__":
    main()

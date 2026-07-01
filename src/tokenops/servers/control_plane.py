"""Control-plane server entrypoint."""

from __future__ import annotations

import os

from tokenops.control_plane.app import create_control_plane_app
from tokenops.a2a.server import run_server


def main() -> None:
    port = int(os.environ.get("TOKENOPS_CONTROL_PLANE_PORT", "8000"))
    run_server(create_control_plane_app(), port)


if __name__ == "__main__":
    main()

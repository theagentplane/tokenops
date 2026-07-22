#!/usr/bin/env python3
"""Start control plane + triad agents (Planner → Researcher → Writer) + product UI."""

from __future__ import annotations

import atexit
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent

os.chdir(ROOT)
os.environ.setdefault("PYTHONPATH", str(ROOT))
os.environ.setdefault("TOKENOPS_CONFIG", "examples/config/triad.yaml")

sys.path.insert(0, str(ROOT))
from tokenops.env import load_env  # noqa: E402

load_env()

PYTHON = sys.executable
UI_PORT = 8501
CONTROL_PLANE_URL = "http://localhost:7700"
PLANNER_URL = "http://localhost:8011"
RESEARCHER_URL = "http://localhost:8012"
WRITER_URL = "http://localhost:8013"

_children: list[subprocess.Popen] = []


def _free_port(port: int) -> None:
    try:
        result = subprocess.run(
            ["lsof", "-tiTCP", f":{port}", "-sTCP:LISTEN"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return
    pids = [p.strip() for p in result.stdout.splitlines() if p.strip()]
    if not pids:
        return
    print(f"Stopping stale listener on port {port} (pid {', '.join(pids)})...")
    for pid in pids:
        try:
            os.kill(int(pid), signal.SIGTERM)
        except (ProcessLookupError, ValueError):
            pass
    time.sleep(0.5)
    try:
        result = subprocess.run(
            ["lsof", "-tiTCP", f":{port}", "-sTCP:LISTEN"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return
    for pid in [p.strip() for p in result.stdout.splitlines() if p.strip()]:
        try:
            os.kill(int(pid), signal.SIGKILL)
        except (ProcessLookupError, ValueError):
            pass


def _shutdown() -> None:
    for proc in reversed(_children):
        if proc.poll() is None:
            proc.terminate()
    for proc in reversed(_children):
        if proc.poll() is None:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


def _start_server(module: str) -> subprocess.Popen:
    env = os.environ.copy()
    proc = subprocess.Popen([PYTHON, "-m", module], cwd=ROOT, env=env)
    _children.append(proc)
    return proc


def _wait_for_health(url: str, name: str, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            response = httpx.get(f"{url.rstrip('/')}/health", timeout=1.0)
            if response.status_code == 200:
                print(f"  {name} ready at {url}")
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise RuntimeError(f"{name} did not become healthy at {url}")


def main() -> int:
    atexit.register(_shutdown)

    def on_signal(signum: int, _frame: object) -> None:
        print("\nShutting down...")
        _shutdown()
        sys.exit(128 + signum)

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    from examples.app_config import load_config

    cfg = load_config()
    for port in {7700, cfg.planner.port, cfg.researcher.port, cfg.writer.port, UI_PORT}:
        _free_port(port)

    os.environ.setdefault("TOKENOPS_URL", CONTROL_PLANE_URL)

    print("Starting control plane...")
    _start_server("tokenops.server")
    print("Starting writer server...")
    _start_server("examples.servers.writer")
    print("Starting researcher server...")
    _start_server("examples.servers.researcher")
    print("Starting planner server...")
    _start_server("examples.servers.planner")

    print("Waiting for services...")
    try:
        _wait_for_health(CONTROL_PLANE_URL, "Control plane")
        _wait_for_health(WRITER_URL, "Writer")
        _wait_for_health(RESEARCHER_URL, "Researcher")
        _wait_for_health(PLANNER_URL, "Planner")
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        _shutdown()
        return 1

    print(f"Starting product UI (Admin + Dashboard) at http://localhost:{UI_PORT}")
    print("Triad entry: Planner at", PLANNER_URL)
    import pathlib
    import tokenops.ui as _tokenops_ui
    ui_app = pathlib.Path(_tokenops_ui.__file__).resolve().parent / "app.py"
    ui = subprocess.run(
        [
            PYTHON,
            "-m",
            "streamlit",
            "run",
            str(ui_app),
            f"--server.port={UI_PORT}",
        ],
        cwd=ROOT,
        env=os.environ.copy(),
    )
    _shutdown()
    return ui.returncode


if __name__ == "__main__":
    raise SystemExit(main())

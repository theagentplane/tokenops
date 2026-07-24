#!/usr/bin/env python3
"""Start control plane + brief agents (Scout → Analyst → Editor)."""

from __future__ import annotations

import atexit
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]

os.chdir(ROOT)
os.environ.setdefault("PYTHONPATH", str(ROOT))
os.environ.setdefault("TOKENOPS_CONFIG", "examples/config/brief.yaml")

# Load wiki .env before spawning children (installed tokenops.load_env may miss repo root).
try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass

sys.path.insert(0, str(ROOT))
from tokenops.env import load_env  # noqa: E402

load_env()

PYTHON = sys.executable
CONTROL_PLANE_URL = "http://localhost:7700"
SCOUT_URL = "http://localhost:8021"
ANALYST_URL = "http://localhost:8022"
EDITOR_URL = "http://localhost:8023"

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
    for port in {7700, cfg.scout.port, cfg.analyst.port, cfg.editor.port}:
        _free_port(port)

    os.environ.setdefault("TOKENOPS_URL", CONTROL_PLANE_URL)

    print("Starting control plane...")
    _start_server("tokenops.server")
    print("Starting editor server...")
    _start_server("examples.servers.editor")
    print("Starting analyst server...")
    _start_server("examples.servers.analyst")
    print("Starting scout server...")
    _start_server("examples.servers.scout")

    print("Waiting for services...")
    try:
        _wait_for_health(CONTROL_PLANE_URL, "Control plane")
        _wait_for_health(EDITOR_URL, "Editor")
        _wait_for_health(ANALYST_URL, "Analyst")
        _wait_for_health(SCOUT_URL, "Scout")
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        _shutdown()
        return 1

    print("Brief stack ready.")
    print(f"  Scout (entry): {SCOUT_URL}")
    print(f"  Analyst:       {ANALYST_URL}")
    print(f"  Editor:        {EDITOR_URL}")
    print(f"  Plane:         {CONTROL_PLANE_URL}")
    print("Ctrl+C to stop.")

    while True:
        for proc in _children:
            code = proc.poll()
            if code is not None:
                print(f"Process exited early (pid={proc.pid}, code={code})", file=sys.stderr)
                _shutdown()
                return code or 1
        time.sleep(1)


if __name__ == "__main__":
    raise SystemExit(main())

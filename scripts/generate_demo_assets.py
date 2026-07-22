#!/usr/bin/env python3
"""Generate demo screenshots, tables, and Playwright screen recordings for the MSFT deck."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "bench" / "demo-assets"
SCREENSHOTS = ASSETS / "screenshots"
VIDEOS = ASSETS / "videos"
TABLES = ASSETS / "tables"

os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("PYTHONPATH", f"{ROOT / 'src'}{os.pathsep}{ROOT}")
os.environ.setdefault("TOKENOPS_CONFIG", "examples/config/default.yaml")

from examples.app_config import load_config  # noqa: E402
from tokenops.control.models import GovernanceMode  # noqa: E402
from tokenops.control.store import Store  # noqa: E402
from tokenops.env import load_env  # noqa: E402
from examples.ui.simulator import run_simulation  # noqa: E402

load_env()

UI_PORT = 8501
UI_BASE = f"http://localhost:{UI_PORT}"
PYTHON = sys.executable

# Streamlit multipage paths (filename-based).
PAGES = {
    "test_bench": "/",
    "admin": "/Admin",
    "dashboard": "/Dashboard",
    "simulator": "/Simulator",
}


def _ensure_dirs() -> None:
    for d in (SCREENSHOTS, VIDEOS, TABLES):
        d.mkdir(parents=True, exist_ok=True)


def _run(cmd: list[str], *, timeout: int | None = None, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=cwd or ROOT,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def reset_db() -> None:
    print("Resetting database...")
    proc = _run([PYTHON, "scripts/db_clear.py"])
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout)
    proc = _run([PYTHON, "scripts/db_reseed.py"])
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout)


def seed_runs() -> None:
    """Populate SQLite with representative runs for the dashboard."""
    print("Seeding simulator runs...")
    store = Store()
    cfg = load_config()

    scenarios = [
        {
            "task": cfg.task,
            "corpus_profile": "healthy",
            "intent": "demo_preview",
            "user_dims": {"user_id": "demo", "team": "growth", "baseline": "tokenops"},
            "governance_mode": GovernanceMode.PREVIEW,
            "demo_mode": True,
        },
        {
            "task": cfg.task,
            "corpus_profile": "leak",
            "intent": "demo_instrumentation_bad",
            "user_dims": {"user_id": "demo", "team": "growth", "baseline": "tokenops"},
            "governance_mode": GovernanceMode.PREVIEW,
            "demo_mode": True,
        },
        {
            "task": cfg.task,
            "corpus_profile": "healthy",
            "intent": "demo_enforced_ok",
            "user_dims": {"user_id": "demo", "team": "growth", "baseline": "tokenops"},
            "governance_mode": GovernanceMode.ENFORCE,
            "demo_mode": True,
        },
        {
            "task": "Summarize token governance ROI for enterprise buyers.",
            "corpus_profile": "leak",
            "intent": "demo_throttle_contrast",
            "user_dims": {"user_id": "demo", "team": "platform", "baseline": "throttle_only"},
            "governance_mode": GovernanceMode.ENFORCE,
            "demo_mode": True,
        },
    ]

    results: list[dict] = []
    for i, sc in enumerate(scenarios, 1):
        print(f"  run {i}/{len(scenarios)}: {sc['intent']}")
        result = run_simulation(
            store,
            task=sc["task"],
            corpus_profile=sc["corpus_profile"],
            intent=sc["intent"],
            user_dims=sc["user_dims"],
            demo_mode=sc["demo_mode"],
            governance_mode=sc["governance_mode"],
        )
        results.append(
            {
                "intent": sc["intent"],
                "status": result.status,
                "halt_reason": result.halt_reason,
                "cost_usd": round(
                    (result.research_cost_micros + result.summarize_cost_micros) / 1_000_000, 6
                ),
                "baseline": sc["user_dims"].get("baseline", ""),
            }
        )

    (TABLES / "seeded_runs.json").write_text(json.dumps(results, indent=2))
    print(f"  seeded {len(results)} runs")


def start_streamlit() -> subprocess.Popen:
    print("Starting Streamlit UI...")
    _run([PYTHON, "-m", "examples.servers.summarize"], timeout=1)  # no-op probe
    # Free port
    subprocess.run(["make", "stop"], cwd=ROOT, capture_output=True, text=True)
    proc = subprocess.Popen(
        [
            PYTHON,
            "-m",
            "streamlit",
            "run",
            "src/tokenops/ui/app.py",
            f"--server.port={UI_PORT}",
            "--server.headless=true",
            "--browser.gatherUsageStats=false",
        ],
        cwd=ROOT,
        env=os.environ.copy(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    deadline = time.time() + 45
    while time.time() < deadline:
        try:
            import urllib.request

            with urllib.request.urlopen(f"{UI_BASE}/_stcore/health", timeout=2) as resp:
                if resp.status == 200:
                    print(f"  UI ready at {UI_BASE}")
                    return proc
        except Exception:
            pass
        if proc.poll() is not None:
            out = proc.stdout.read() if proc.stdout else ""
            raise RuntimeError(f"Streamlit exited early:\n{out}")
        time.sleep(0.5)
    proc.kill()
    raise RuntimeError("Streamlit did not become healthy in time")


def capture_ui_assets(ui_proc: subprocess.Popen) -> None:
    from playwright.sync_api import sync_playwright

    print("Capturing UI screenshots and videos with Playwright...")

    static_shots = [
        ("A3_ui_nav", PAGES["test_bench"]),
        ("B2_registration", PAGES["simulator"]),
        ("B3_effective_governance", PAGES["admin"]),
        ("C1_preview_mode", PAGES["simulator"]),
        ("C6_active_governance", PAGES["dashboard"]),
        ("D9_policy_admin_templates", PAGES["admin"]),
        ("E1_dashboard_green", PAGES["dashboard"]),
        ("G1_test_bench_config", PAGES["test_bench"]),
    ]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # Static screenshots
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        for name, path in static_shots:
            url = f"{UI_BASE}{path}"
            print(f"  screenshot: {name}")
            page.goto(url, wait_until="networkidle", timeout=60_000)
            time.sleep(2)
            if name == "C1_preview_mode":
                # Expand preview toggle context — sidebar visible on simulator page.
                page.screenshot(path=str(SCREENSHOTS / f"{name}.png"), full_page=True)
            elif name == "C6_active_governance":
                try:
                    page.get_by_text("Active governance (read-only)").click(timeout=3000)
                    time.sleep(0.5)
                except Exception:
                    pass
                page.screenshot(path=str(SCREENSHOTS / f"{name}.png"), full_page=True)
            else:
                page.screenshot(path=str(SCREENSHOTS / f"{name}.png"), full_page=True)
        page.close()

        # Simulator preview run video
        print("  video: C2_simulator_preview_run")
        ctx = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            record_video_dir=str(VIDEOS / "_raw"),
            record_video_size={"width": 1920, "height": 1080},
        )
        vid_page = ctx.new_page()
        vid_page.goto(f"{UI_BASE}{PAGES['simulator']}", wait_until="networkidle", timeout=60_000)
        time.sleep(1)
        # Enable preview mode if possible
        try:
            labels = vid_page.locator("label")
            for i in range(labels.count()):
                txt = labels.nth(i).inner_text(timeout=500)
                if "Preview mode" in txt:
                    labels.nth(i).click()
                    break
        except Exception:
            pass
        try:
            vid_page.get_by_role("button", name="Start run").click(timeout=5000)
        except Exception:
            vid_page.locator("button:has-text('Start run')").first.click(timeout=5000)
        time.sleep(12)
        vid_page.screenshot(path=str(SCREENSHOTS / "C3_policy_signals.png"), full_page=True)
        try:
            vid_page.get_by_role("tab", name="Control plane").click(timeout=5000)
            time.sleep(1)
            vid_page.screenshot(path=str(SCREENSHOTS / "C3_control_plane_tab.png"), full_page=True)
        except Exception:
            pass
        video = vid_page.video
        vid_page.close()
        ctx.close()
        if video:
            target = VIDEOS / "C2_simulator_preview_run.webm"
            video.save_as(str(target))
            print(f"    saved {target}")

        # Dashboard problematic filter
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        page.goto(f"{UI_BASE}{PAGES['dashboard']}", wait_until="networkidle", timeout=60_000)
        time.sleep(1)
        try:
            page.get_by_text("Problematic only").click(timeout=3000)
            time.sleep(0.5)
        except Exception:
            pass
        page.screenshot(path=str(SCREENSHOTS / "E2_dashboard_problematic.png"), full_page=True)
        page.close()

        browser.close()


def run_benchmark_tables() -> bool:
    """Run live benchmark sweep; return True if tables were produced."""
    sweep_json = TABLES / "showcase_sweep.json"
    browser_py = ROOT / "benchmarking" / "browseruse" / ".venv" / "bin" / "python"
    if not browser_py.is_file():
        print("  browser-use venv missing — skipping live benchmark")
        return False

    print("Running browser-use showcase benchmark (trials=1, may take several minutes)...")
    proc = _run(
        [
            str(browser_py),
            str(ROOT / "benchmarking" / "run_trials_sweep.py"),
            "--suite",
            "showcase_suite",
            "--framework",
            "browseruse",
            "--trial-counts",
            "1",
            "--cooldown-sec",
            "30",
            "--jobs",
            "1",
            "--parallel-batch",
            "1",
            "--out",
            str(sweep_json),
        ],
        timeout=900,
    )
    (TABLES / "benchmark_stdout.txt").write_text(proc.stdout or "")
    (TABLES / "benchmark_stderr.txt").write_text(proc.stderr or "")
    if proc.returncode != 0:
        print(f"  benchmark failed (code {proc.returncode})")
        return False
    return sweep_json.is_file()


def build_tables_from_sweep() -> None:
    sweep_json = TABLES / "showcase_sweep.json"
    if not sweep_json.is_file():
        print("  no sweep JSON — building illustrative tables from docs")
        _build_illustrative_tables()
        return

    data = json.loads(sweep_json.read_text())
    rows = data if isinstance(data, list) else [data]

    # H1: spend reduction
    spend_lines = ["| Framework | Scenario | Trials | Vanilla avg $ | TokenOps avg $ | Reduction % | Showcase pass |",
                   "|---|---|---:|---:|---:|---:|---|"]
    success_lines = ["| Framework | Scenario | Trials | Vanilla success@cap | TokenOps success@cap | Delta |",
                     "|---|---|---:|---:|---:|---:|"]

    for row in rows:
        fw = row.get("framework", "")
        scenario = row.get("scenario", "")
        trials = row.get("trials", "")
        ug = row.get("ungoverned", {}) or {}
        to = row.get("tokenops", {}) or {}
        ug_avg = ug.get("avg_spend_usd", ug.get("avg_spend", ""))
        to_avg = to.get("avg_spend_usd", to.get("avg_spend", ""))
        pct = row.get("spend_reduction_pct", "")
        showcase = row.get("showcase_pass", "")
        spend_lines.append(f"| {fw} | {scenario} | {trials} | {ug_avg} | {to_avg} | {pct} | {showcase} |")

        ug_succ = ug.get("success_within_budget", ug.get("successes", ""))
        to_succ = to.get("success_within_budget", to.get("successes", ""))
        try:
            delta = ""
            if ug_succ != "" and to_succ != "" and float(ug_succ) > 0:
                delta = f"{((float(to_succ) - float(ug_succ)) / float(ug_succ) * 100):.1f}%"
        except (TypeError, ValueError):
            delta = ""
        success_lines.append(f"| {fw} | {scenario} | {trials} | {ug_succ} | {to_succ} | {delta} |")

    (TABLES / "H1_average_spend_reduction.md").write_text("\n".join(spend_lines) + "\n")
    (TABLES / "H2_success_rate_vs_throttle.md").write_text("\n".join(success_lines) + "\n")
    (TABLES / "H3_cross_bench_summary.md").write_text(
        "# Cross-bench summary\n\nSee `showcase_sweep.json` for full payload.\n"
    )
    print("  wrote KPI tables from sweep JSON")


def _build_illustrative_tables() -> None:
    """Fallback when live benchmarks cannot run."""
    spend = """| Arm | Avg spend (USD) | Median spend | Notes |
|---|---:|---:|---|
| Ungoverned | 0.042 | 0.039 | Runaway reload trap |
| Throttle only | 0.034 | 0.034 | Hard cap, incomplete |
| TokenOps | 0.024 | 0.023 | Steer + complete |
"""
    success = """| Arm | Success within budget | Completed runs |
|---|---:|---:|
| Ungoverned | 2/5 | 3/5 |
| Throttle only | 1/5 | 1/5 |
| TokenOps | 4/5 | 4/5 |
"""
    (TABLES / "H1_average_spend_reduction.md").write_text(
        "# Average spend reduction (ILLUSTRATIVE — re-run sweep for live data)\n\n" + spend
    )
    (TABLES / "H2_success_rate_vs_throttle.md").write_text(
        "# Success rate vs throttle (ILLUSTRATIVE — re-run sweep for live data)\n\n" + success
    )
    (TABLES / "H3_cross_bench_summary.md").write_text(
        "# Cross-bench summary\n\nLive sweep did not complete. Run:\n\n"
        "```bash\npython benchmarking/run_trials_sweep.py --suite showcase_suite --framework both "
        "--trial-counts 1,3,5 --cooldown-sec 90 --out examples/demo-assets/tables/showcase_sweep.json\n```\n"
    )


def write_manifest() -> None:
    shots = sorted(p.name for p in SCREENSHOTS.glob("*.png"))
    vids = sorted(p.name for p in VIDEOS.glob("*") if p.is_file())
    tables = sorted(p.name for p in TABLES.glob("*") if p.is_file())
    manifest = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "screenshots": shots,
        "videos": vids,
        "tables": tables,
        "notes": {
            "videos": "Playwright records WebM. Convert with: ffmpeg -i in.webm -pix_fmt yuv420p out.mp4",
            "live_benchmark": "Set OPENAI_API_KEY and run full sweep for production tables.",
        },
    }
    (ASSETS / "MANIFEST.json").write_text(json.dumps(manifest, indent=2))
    readme = f"""# Demo assets

Generated by `scripts/generate_demo_assets.py`.

## Screenshots ({len(shots)})
{chr(10).join('- ' + s for s in shots)}

## Videos ({len(vids)})
{chr(10).join('- ' + s for s in vids) or '- (none yet)'}

## Tables
{chr(10).join('- ' + t for t in tables)}

## Re-generate
```bash
python scripts/generate_demo_assets.py
```
"""
    (ASSETS / "README.md").write_text(readme)


def main() -> int:
    _ensure_dirs()
    reset_db()
    seed_runs()
    ui_proc = start_streamlit()
    try:
        capture_ui_assets(ui_proc)
    finally:
        ui_proc.terminate()
        try:
            ui_proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            ui_proc.kill()

    ok = run_benchmark_tables()
    build_tables_from_sweep()
    write_manifest()
    print(f"\nDone. Assets in {ASSETS}")
    if not ok:
        print("Note: live benchmark did not finish — tables may be illustrative.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

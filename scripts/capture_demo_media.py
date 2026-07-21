#!/usr/bin/env python3
"""Capture code screenshots and Playwright videos for the Chat governance demo."""

from __future__ import annotations

import html
import os
import re
import sys
import time
from pathlib import Path

_RUN_ID_RE = re.compile(r"run_[0-9a-f]{8}")

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "bench" / "demo-assets"
CODE_SHOTS = ASSETS / "code"
VIDEOS = ASSETS / "videos"
UI_BASE = "http://localhost:8501"
DASHBOARD_URL = f"{UI_BASE}/dashboard"
CHAT_URL = UI_BASE

# Recording pacing (seconds)
ACTION_PAUSE = 2.5
SCENARIO_PAUSE = 5.0
RESULT_DWELL = 4.0

# Theme (matches src/tokenops/ui/theme.py)
GOLD = "#C9A227"
INK = "#0A0A0A"
MUTED = "#9A9588"

SCENARIOS = [
    {
        "id": "01_governance_off_spend_exceed",
        "gov_on": False,
        "chip": "Compare five enterprise SaaS pricing pages in full detail.",
        "expect": "Governance OFF",
        "banner_title": "Scenario 1 · Governance OFF — Spend Exceed",
        "banner_sub": "Preview mode — run completes over the budget cap",
    },
    {
        "id": "02_governance_on_budget_cap",
        "gov_on": True,
        "chip": "Compare five enterprise SaaS pricing pages in full detail.",
        "expect": "budget cap",
        "banner_title": "Scenario 2 · Governance ON — Budget Cap",
        "banner_sub": "Enforce mode — pre_call worst-case halts the run",
    },
    {
        "id": "03_governance_on_cost_guard",
        "gov_on": True,
        "chip": "Give a quick overview of enterprise SaaS pricing.",
        "expect": "cost guard",
        "banner_title": "Scenario 3 · Governance ON — Cost Guard",
        "banner_sub": "Enforce mode — minimize steering injected at 80% budget",
    },
]

os.chdir(ROOT)
sys.path.insert(0, str(ROOT / "src"))

CODE_SNIPPETS = [
    {
        "name": "01_boundary_search_tool",
        "title": "@boundary — tool hook (search)",
        "file": "bench/agents/research/native/agent.py",
        "start": 36,
        "end": 53,
        "highlight": {36, 37, 41},
    },
    {
        "name": "02_wrap_complete_server",
        "title": "wrap_complete — LLM hook in research server",
        "file": "bench/agents/research/native/server.py",
        "start": 88,
        "end": 100,
        "highlight": {97, 98, 99},
    },
    {
        "name": "03_wrap_complete_integration",
        "title": "wrap_complete — pre_call governance + dispatch",
        "file": "src/tokenops/control/integration.py",
        "start": 196,
        "end": 264,
        "highlight": {196, 232, 239, 253},
    },
    {
        "name": "04_governor_setup",
        "title": "Governor setup — budgets, ledger, policy registration",
        "file": "src/tokenops/control/config.py",
        "start": 113,
        "end": 147,
        "highlight": {126, 129, 130, 133, 144, 145, 147},
    },
]


def _read_lines(path: Path, start: int, end: int) -> list[tuple[int, str]]:
    lines = path.read_text().splitlines()
    return [(i, lines[i - 1]) for i in range(start, min(end, len(lines)) + 1)]


def _code_html(snippet: dict) -> str:
    path = ROOT / snippet["file"]
    rows = _read_lines(path, snippet["start"], snippet["end"])
    highlight = set(snippet.get("highlight", []))
    body = []
    for lineno, text in rows:
        cls = "line highlight" if lineno in highlight else "line"
        body.append(
            f'<div class="{cls}">'
            f'<span class="ln">{lineno}</span>'
            f'<code>{html.escape(text) or " "}</code></div>'
        )
    rel = snippet["file"]
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"/>
<style>
  body {{ margin: 0; background: #0d0d0d; color: #e8e4d9; font-family: "SF Mono", Menlo, Consolas, monospace; }}
  .frame {{ padding: 28px 32px; max-width: 1100px; }}
  .title {{ color: #c9a227; font-size: 15px; font-weight: 600; margin-bottom: 6px; }}
  .path {{ color: #7a7568; font-size: 12px; margin-bottom: 18px; }}
  .code {{ background: #141414; border: 1px solid #2a2820; border-radius: 10px; padding: 16px 0; }}
  .line {{ display: flex; gap: 16px; padding: 2px 20px; font-size: 13px; line-height: 1.55; }}
  .line.highlight {{ background: rgba(201, 162, 39, 0.14); border-left: 3px solid #c9a227; padding-left: 17px; }}
  .ln {{ color: #5c584e; min-width: 36px; text-align: right; user-select: none; }}
  code {{ white-space: pre; }}
</style></head>
<body><div class="frame">
  <div class="title">{html.escape(snippet["title"])}</div>
  <div class="path">{html.escape(rel)}</div>
  <div class="code">{''.join(body)}</div>
</div></body></html>"""


def capture_code_screenshots() -> None:
    from playwright.sync_api import sync_playwright

    CODE_SHOTS.mkdir(parents=True, exist_ok=True)
    tmp = ASSETS / "_code_html"
    tmp.mkdir(parents=True, exist_ok=True)

    print("Capturing code screenshots...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1200, "height": 900})
        for snip in CODE_SNIPPETS:
            html_path = tmp / f"{snip['name']}.html"
            html_path.write_text(_code_html(snip))
            page.goto(html_path.as_uri(), wait_until="load")
            out = CODE_SHOTS / f"{snip['name']}.png"
            page.locator(".frame").screenshot(path=str(out))
            print(f"  {out.name}")
        browser.close()


def _pause(seconds: float = ACTION_PAUSE) -> None:
    time.sleep(seconds)


def _inject_scenario_banner(page, title: str, subtitle: str = "") -> None:
    """Fixed gold/black banner rendered into the page (captured by Playwright video)."""
    page.evaluate(
        """([title, subtitle, gold, ink, muted]) => {
            let el = document.getElementById('tokenops-demo-banner');
            if (!el) {
                el = document.createElement('div');
                el.id = 'tokenops-demo-banner';
                el.style.cssText = [
                    'position:fixed', 'top:0', 'left:0', 'right:0', 'z-index:999999',
                    `background:linear-gradient(180deg, ${ink} 0%, rgba(10,10,10,0.96) 100%)`,
                    `border-bottom:2px solid ${gold}`,
                    'padding:14px 32px', 'pointer-events:none',
                    'font-family:system-ui,-apple-system,BlinkMacSystemFont,sans-serif',
                    'box-shadow:0 4px 24px rgba(0,0,0,0.45)',
                ].join(';');
                document.body.appendChild(el);
            }
            const sub = subtitle
                ? `<div style="color:${muted};font-size:13px;margin-top:5px;font-weight:500;">${subtitle}</div>`
                : '';
            el.innerHTML =
                `<div style="color:${gold};font-size:17px;font-weight:700;letter-spacing:0.05em;text-transform:uppercase;">${title}</div>` +
                sub;
        }""",
        [title, subtitle, GOLD, INK, MUTED],
    )


def _set_governance_slider(page, on: bool) -> None:
    slider = page.get_by_label("Governance mode (0=OFF, 1=ON)")
    target = "1" if on else "0"
    current = slider.get_attribute("aria-valuenow") or "1"
    if current != target:
        slider.focus()
        key = "ArrowRight" if on else "ArrowLeft"
        slider.press(key)
    _pause()


def _click_chip(page, label_substr: str) -> None:
    page.get_by_role("button", name=label_substr).click()
    _pause()


def _wait_for_run(page, expect: str, timeout_ms: int = 180_000) -> None:
    """Wait for the live governance banner (not static chip hints)."""
    selectors = {
        "Governance OFF": "text=Governance OFF — run completed",
        "budget cap": "text=Governance · budget cap",
        "cost guard": "text=Governance · cost guard",
    }
    sel = selectors.get(expect, f"text={expect}")
    page.wait_for_selector(sel, timeout=timeout_ms)
    page.wait_for_selector("text=Run ID:", timeout=timeout_ms)
    _pause(RESULT_DWELL)


def _run_id_from_chat(page) -> str:
    marker = page.locator("#tokenops-run-id")
    if marker.count():
        rid = marker.last.get_attribute("data-run-id")
        if rid:
            return rid.strip()
    loc = page.locator("text=Run ID:")
    if loc.count() == 0:
        return ""
    m = _RUN_ID_RE.search(loc.last.inner_text())
    return m.group(0) if m else ""


def _scroll_to_governance_trace(page) -> None:
    heading = page.get_by_role("heading", name="Governance trace")
    heading.scroll_into_view_if_needed()
    _pause()


def _show_dashboard_run(
    page,
    run_id: str,
    *,
    expect: str,
    banner_title: str = "",
    banner_sub: str = "",
) -> None:
    page.goto(f"{DASHBOARD_URL}?run_id={run_id}", wait_until="networkidle", timeout=60_000)
    if banner_title:
        _inject_scenario_banner(page, banner_title, banner_sub)
        _pause()
    page.wait_for_selector("text=Run detail", timeout=30_000)
    page.wait_for_selector("text=Governance trace", timeout=30_000)
    _scroll_to_governance_trace(page)
    if expect == "budget cap":
        try:
            page.get_by_text("Halt detail").click(timeout=3000)
            _pause()
        except Exception:
            pass
    elif expect in ("cost guard", "Governance OFF"):
        try:
            page.get_by_text("Steering detail").click(timeout=3000)
            _pause()
        except Exception:
            pass
    _pause(RESULT_DWELL)


def _run_scenario(page, sc: dict, *, first: bool) -> None:
    if not first:
        _pause(SCENARIO_PAUSE)
        page.goto(CHAT_URL, wait_until="networkidle", timeout=60_000)
        _pause()

    _inject_scenario_banner(page, sc["banner_title"], sc["banner_sub"])
    _pause()

    before_id = _run_id_from_chat(page)
    _set_governance_slider(page, sc["gov_on"])
    _click_chip(page, sc["chip"])
    _wait_for_run(page, sc["expect"])

    # Make sure we select the exact run we just produced.
    run_id = _run_id_from_chat(page)
    for _ in range(10):
        if run_id and run_id != before_id:
            break
        time.sleep(0.5)
        run_id = _run_id_from_chat(page)

    if not run_id:
        raise RuntimeError(f"Could not read run_id after scenario {sc['id']}")

    _show_dashboard_run(
        page,
        run_id,
        expect=sc["expect"],
        banner_title=sc["banner_title"],
        banner_sub=sc["banner_sub"],
    )
    page.screenshot(path=str(VIDEOS / f"{sc['id']}.png"), full_page=True)


def capture_combined_demo_video(*, only: str | None = None) -> None:
    from playwright.sync_api import sync_playwright

    VIDEOS.mkdir(parents=True, exist_ok=True)
    raw_dir = VIDEOS / "_raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    scenarios = SCENARIOS
    if only:
        scenarios = [s for s in SCENARIOS if s["id"] == only or s["id"].startswith(only)]
        if not scenarios:
            raise SystemExit(f"Unknown scenario: {only}")

    out_name = (
        "governance_demo_all_scenarios.webm"
        if len(scenarios) == len(SCENARIOS)
        else f"{scenarios[0]['id']}.webm"
    )

    print(f"Recording demo video → {out_name} ({len(scenarios)} scenario(s), live LLM)...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            viewport={"width": 1440, "height": 900},
            record_video_dir=str(raw_dir),
            record_video_size={"width": 1440, "height": 900},
        )
        page = ctx.new_page()
        page.goto(CHAT_URL, wait_until="networkidle", timeout=60_000)
        _pause()

        for i, sc in enumerate(scenarios):
            _run_scenario(page, sc, first=(i == 0))

        video = page.video
        page.close()
        if video:
            target = VIDEOS / out_name
            video.save_as(str(target))
            print(f"  saved {target}")
        ctx.close()
        browser.close()


def capture_scenario_videos(*, only: str | None = None) -> None:
    """Record one continuous demo video (all scenarios by default)."""
    capture_combined_demo_video(only=only)


def main() -> int:
    import argparse
    import urllib.request

    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="Re-record one scenario (e.g. 03_governance_on_cost_guard)")
    parser.add_argument("--videos-only", action="store_true")
    parser.add_argument("--code-only", action="store_true")
    args = parser.parse_args()

    try:
        if not args.code_only:
            with urllib.request.urlopen(f"{UI_BASE}/_stcore/health", timeout=3) as r:
                if r.status != 200:
                    print("Streamlit not healthy — run `make run` first")
                    return 1
    except Exception:
        if not args.code_only:
            print("Streamlit not reachable at", UI_BASE, "— run `make run` first")
            return 1

    if not args.videos_only:
        capture_code_screenshots()
    if not args.code_only:
        capture_scenario_videos(only=args.only)
    print(f"\nAssets written to {ASSETS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

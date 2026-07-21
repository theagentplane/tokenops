#!/usr/bin/env python3
"""Render the archived 9-run benchmark table as a gold/black PNG.

Source table: bench/demo-assets/tables/archive/browseruse_benchmark_results.md
"""

from __future__ import annotations

import html
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "bench" / "demo-assets" / "tables" / "archive" / "browseruse_benchmark_results.md"
OUT = ROOT / "bench" / "demo-assets" / "tables" / "overall_9_runs_benchmark.png"

# Theme (matches src/tokenops/ui/theme.py)
GOLD = "#C9A227"
INK = "#0A0A0A"
PANEL = "#121212"
MUTED = "#9A9588"
TEXT = "#E8E4D9"
BORDER = "#2A2820"

_SCENARIO_DESC: dict[str, str] = {
    # Keep these tight—slide labels, not paragraphs.
    "books_verify_trap": "Runaway tab-reload loop (verify trap)",
    "pricing_model_routing": "Model routing overhead (multi-call planner)",
    "pricing_quick_verify_trap": "Quick verify loop (re-check trap)",
}

_WITHIN_RE = re.compile(r"(\d+)\s*/\s*(\d+)\s*·\s*(\d+)\s*/\s*(\d+)")

# Benchmark agent frameworks (stars refreshed at render time when GitHub API is reachable).
BENCHMARK_REPOS: list[tuple[str, str, str, int]] = [
    ("browser-use", "browser-use", "browser-use", 102_136),
    ("MetaGPT", "FoundationAgents", "MetaGPT", 69_149),
]

# "Standard rate limiting" proxy baseline (illustrative numbers used in repo docs)
# - throttle-only: within-budget success is lower due to hard stopping with no steering.
_THROTTLE_ONLY_SUCCESS = (1, 5)  # 20%
_TOKENOPS_SUCCESS_ILLUSTRATIVE = (4, 5)  # 80%


def _parse_markdown_table(md: str) -> tuple[list[str], list[list[str]]]:
    lines = [ln.strip() for ln in md.splitlines() if ln.strip()]
    # Find first markdown table header row (starts/ends with |).
    start = next(i for i, ln in enumerate(lines) if ln.startswith("|") and ln.endswith("|"))
    header = [c.strip() for c in lines[start].strip("|").split("|")]
    # Skip alignment row.
    body: list[list[str]] = []
    for ln in lines[start + 2 :]:
        if not (ln.startswith("|") and ln.endswith("|")):
            break
        row = [c.strip() for c in ln.strip("|").split("|")]
        if len(row) != len(header):
            continue
        body.append(row)
    return header, body


def _parse_money(s: str) -> float:
    # "$0.176" -> 0.176
    return float(s.strip().replace("$", "").replace(",", ""))


def _fmt_stars(n: int) -> str:
    if n >= 10_000:
        return f"{n / 1000:.1f}k".replace(".0k", "k")
    return f"{n:,}"


def _resolve_repo_stars() -> list[tuple[str, str, int]]:
    """Return (display_name, github_path, stars) for footer."""
    import json
    import urllib.error
    import urllib.request

    out: list[tuple[str, str, int]] = []
    for label, owner, repo, fallback in BENCHMARK_REPOS:
        stars = fallback
        try:
            req = urllib.request.Request(
                f"https://api.github.com/repos/{owner}/{repo}",
                headers={"Accept": "application/vnd.github+json"},
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode())
                stars = int(data.get("stargazers_count", fallback))
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError):
            pass
        out.append((label, f"github.com/{owner}/{repo}", stars))
    return out


def _repo_footer_html() -> str:
    rows = []
    for label, path, stars in _resolve_repo_stars():
        rows.append(
            f'<div class="repo-row">'
            f'<span class="repo-name">{html.escape(label)}</span>'
            f'<span class="repo-path">{html.escape(path)}</span>'
            f'<span class="repo-stars">★ {_fmt_stars(stars)}</span>'
            f"</div>"
        )
    return (
        '<div class="repo-footer">'
        '<div class="repo-footer-label">Agents benchmarked</div>'
        + "".join(rows)
        + "</div>"
    )


def _hero_metrics(cols: list[str], rows: list[list[str]]) -> dict[str, str]:
    """Compute slide headline metrics from the 9-row table (weighted by N)."""
    idx_n = cols.index("N")
    idx_v = cols.index("Vanilla avg")
    idx_t = cols.index("TokenOps avg")
    idx_within = cols.index("Within cap (V/T)")

    total_n = 0
    vanilla_spend = 0.0
    tokenops_spend = 0.0
    v_ok = 0
    t_ok = 0
    for r in rows:
        n = int(r[idx_n])
        total_n += n
        vanilla_spend += _parse_money(r[idx_v]) * n
        tokenops_spend += _parse_money(r[idx_t]) * n
        m = _WITHIN_RE.search(r[idx_within])
        if m:
            v_ok += int(m.group(1))
            # denom is group(2) == n (per-row); total denom uses total_n
            t_ok += int(m.group(3))

    v_avg = 0.0 if total_n <= 0 else vanilla_spend / total_n
    t_avg = 0.0 if total_n <= 0 else tokenops_spend / total_n
    spend_drop_pct = 0.0 if vanilla_spend <= 0 else (1.0 - (tokenops_spend / vanilla_spend)) * 100.0
    v_rate = 0.0 if total_n <= 0 else (v_ok / total_n) * 100.0
    t_rate = 0.0 if total_n <= 0 else (t_ok / total_n) * 100.0
    delta_pp = t_rate - v_rate

    return {
        "avg_spend": f"↓ {spend_drop_pct:.1f}% · ${v_avg:.3f} → ${t_avg:.3f}",
        "avg_spend_note": f"Total spend (weighted): ${vanilla_spend:.3f} → ${tokenops_spend:.3f} over N={total_n}",
        "complete": f"{v_rate:.0f}% → {t_rate:.0f}%",
        "complete_note": f"Within-cap success: {v_ok}/{total_n} → {t_ok}/{total_n} ({delta_pp:+.0f} pp)",
    }


def _html_table(cols: list[str], rows: list[list[str]]) -> str:
    thead = "".join(f'<th class="th">{html.escape(c)}</th>' for c in cols)
    scenario_idx = cols.index("Scenario") if "Scenario" in cols else -1
    metrics = _hero_metrics(cols, rows)

    def td(val: str) -> str:
        v = val.strip()
        cls = "td"
        # A couple semantic highlights for the demo table.
        if v in ("✅", "Yes", "yes"):
            cls += " ok"
        if v in ("—",):
            cls += " muted"
        return f'<td class="{cls}">{html.escape(v)}</td>'

    cooked: list[list[str]] = []
    for r in rows:
        rr = list(r)
        if scenario_idx >= 0 and scenario_idx < len(rr):
            rr[scenario_idx] = _SCENARIO_DESC.get(rr[scenario_idx], rr[scenario_idx])
        cooked.append(rr)
    tbody = "".join("<tr>" + "".join(td(v) for v in r) + "</tr>" for r in cooked)

    title = "TokenOps Benchmark — Overall (9 runs)"
    subtitle = "Archived A/B sweeps (ungoverned vs tokenops) — slide table (gold/black)"

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"/>
<style>
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    background: {INK};
    color: {TEXT};
    font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  }}
  .frame {{
    padding: 34px 36px 30px;
    max-width: 1500px;
  }}
  .title {{
    color: {GOLD};
    font-size: 22px;
    font-weight: 800;
    letter-spacing: 0.04em;
    margin: 0 0 6px 0;
  }}
  .subtitle {{
    color: {MUTED};
    font-size: 13px;
    margin: 0 0 18px 0;
  }}
  .hero {{
    display: flex;
    gap: 12px;
    margin: 12px 0 16px 0;
  }}
  .hero .metric {{ flex: 1; }}
  .metric {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 12px;
    padding: 10px 12px;
  }}
  .metric .k {{
    color: {MUTED};
    font-size: 11px;
    font-weight: 800;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }}
  .metric .v {{
    color: {GOLD};
    font-size: 18px;
    font-weight: 900;
    margin-top: 4px;
  }}
  .metric .n {{
    color: {MUTED};
    font-size: 11.5px;
    margin-top: 4px;
    line-height: 1.35;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 12px;
    overflow: hidden;
    font-size: 12px;
  }}
  .th {{
    text-align: left;
    padding: 10px 12px;
    color: {GOLD};
    font-weight: 800;
    background: rgba(201, 162, 39, 0.10);
    border-bottom: 2px solid {GOLD};
    white-space: nowrap;
  }}
  .td {{
    padding: 9px 12px;
    border-bottom: 1px solid {BORDER};
    vertical-align: top;
    line-height: 1.35;
  }}
  tr:last-child .td {{ border-bottom: none; }}
  .td.ok {{ color: #81C784; font-weight: 700; }}
  .td.muted {{ color: {MUTED}; }}
  .repo-footer {{
    margin-top: 14px;
    padding-top: 10px;
    border-top: 1px solid {BORDER};
    max-width: 520px;
  }}
  .repo-footer-label {{
    color: {MUTED};
    font-size: 10px;
    font-weight: 800;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    margin-bottom: 6px;
  }}
  .repo-row {{
    display: flex;
    align-items: baseline;
    gap: 10px;
    font-size: 11px;
    line-height: 1.6;
    flex-wrap: wrap;
  }}
  .repo-name {{
    color: {TEXT};
    font-weight: 700;
    min-width: 88px;
  }}
  .repo-path {{
    color: {MUTED};
    font-family: ui-monospace, Menlo, monospace;
    font-size: 10.5px;
  }}
  .repo-stars {{
    color: {GOLD};
    font-weight: 800;
    margin-left: auto;
  }}
</style></head>
<body><div class="frame">
  <div class="title">{html.escape(title)}</div>
  <div class="subtitle">{html.escape(subtitle)}</div>
  <div class="hero">
    <div class="metric">
      <div class="k">Average spend</div>
      <div class="v">{metrics["avg_spend"]}</div>
      <div class="n">{html.escape(metrics["avg_spend_note"])}</div>
    </div>
    <div class="metric">
      <div class="k">Completion under cap</div>
      <div class="v">{metrics["complete"]}</div>
      <div class="n">{html.escape(metrics["complete_note"])}</div>
    </div>
  </div>
  <table>
    <thead><tr>{thead}</tr></thead>
    <tbody>{tbody}</tbody>
  </table>
  {_repo_footer_html()}
</div></body></html>"""


def main() -> int:
    from playwright.sync_api import sync_playwright

    if not SRC.is_file():
        raise SystemExit(f"Missing source markdown: {SRC}")
    cols, rows = _parse_markdown_table(SRC.read_text())

    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = ROOT / "bench" / "demo-assets" / "_code_html" / "overall_9_runs_benchmark.html"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(_html_table(cols, rows))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 900})
        page.goto(tmp.as_uri(), wait_until="load")
        page.locator(".frame").screenshot(path=str(OUT))
        browser.close()

    print(f"Wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


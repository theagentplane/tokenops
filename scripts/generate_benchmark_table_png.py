#!/usr/bin/env python3
"""Render the overall demo benchmark table as a gold/black PNG."""

from __future__ import annotations

import html
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "bench" / "demo-assets" / "tables" / "overall_benchmark_table.png"

# Theme (matches src/tokenops/ui/theme.py)
GOLD = "#C9A227"
INK = "#0A0A0A"
PANEL = "#121212"
MUTED = "#9A9588"
TEXT = "#E8E4D9"
BORDER = "#2A2820"

TITLE = "TokenOps Benchmark — Native Research → Summarize"
SUBTITLE = "gpt-4o-mini · corpus backend · live + simulator runs"

COLUMNS = (
    "Benchmark",
    "Governance",
    "Budget cap",
    "Run spend",
    "Within cap?",
    "Outcome / policy",
)

ROWS = [
    {
        "benchmark": "Shared ledger — before",
        "governance": "Separate ledgers",
        "cap": "$0.0010",
        "spend": "$0.0012",
        "within": "No",
        "outcome": "Completed over cap",
        "highlight": False,
    },
    {
        "benchmark": "Shared ledger — after",
        "governance": "TokenOps enforce",
        "cap": "$0.0010",
        "spend": "$0.0008",
        "within": "Yes",
        "outcome": "pre_call_worst_case HALT",
        "highlight": True,
    },
    {
        "benchmark": "Live demo — spend exceed",
        "governance": "OFF (preview)",
        "cap": "$0.0001",
        "spend": "~$0.0002",
        "within": "No",
        "outcome": "Completed; policies detected, not enforced",
        "highlight": False,
    },
    {
        "benchmark": "Live demo — budget cap",
        "governance": "ON (enforce)",
        "cap": "$0.0001",
        "spend": "$0.0000",
        "within": "Yes",
        "outcome": "pre_call_worst_case HALT",
        "highlight": True,
    },
    {
        "benchmark": "Live demo — cost guard",
        "governance": "ON (enforce)",
        "cap": "$0.00018",
        "spend": "~$0.00017",
        "within": "Yes",
        "outcome": "cost_guard INJECT at ~80% budget",
        "highlight": True,
    },
]

FOOTNOTES = [
    "Shared ledger rows: reproducible simulator demo (prep_ledger_comparison.py).",
    "Live demo rows: Chat chips with calibrated budgets (scripts/test_demo_scenarios.py).",
    "Frame as architecture proof — not multi-trial production ROI.",
]


def _within_span(value: str) -> str:
    cls = "within-yes" if value.lower().startswith("y") else "within-no"
    return f'<span class="{cls}">{html.escape(value)}</span>'


def _row_html(row: dict) -> str:
    hl = " highlight" if row.get("highlight") else ""
    vals = [
        row["benchmark"],
        row["governance"],
        row["cap"],
        row["spend"],
        _within_span(row["within"]),
        row["outcome"],
    ]
    cells = []
    for i, v in enumerate(vals):
        inner = html.escape(v) if i != 4 else v  # within column already escaped in span
        cells.append(f'<td class="td{hl}">{inner}</td>')
    return "<tr>" + "".join(cells) + "</tr>"


def _table_html() -> str:
    head = "".join(f'<th class="th">{html.escape(c)}</th>' for c in COLUMNS)
    body = "".join(_row_html(r) for r in ROWS)
    foot = "".join(f"<li>{html.escape(n)}</li>" for n in FOOTNOTES)
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
    padding: 36px 40px 32px;
    max-width: 1180px;
  }}
  .title {{
    color: {GOLD};
    font-size: 22px;
    font-weight: 700;
    letter-spacing: 0.04em;
    margin: 0 0 6px 0;
  }}
  .subtitle {{
    color: {MUTED};
    font-size: 13px;
    margin: 0 0 22px 0;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 12px;
    overflow: hidden;
    font-size: 13px;
  }}
  .th {{
    text-align: left;
    padding: 12px 14px;
    color: {GOLD};
    font-weight: 700;
    background: rgba(201, 162, 39, 0.10);
    border-bottom: 2px solid {GOLD};
    white-space: nowrap;
  }}
  .td {{
    padding: 11px 14px;
    border-bottom: 1px solid {BORDER};
    vertical-align: top;
    line-height: 1.45;
  }}
  tr:last-child .td {{ border-bottom: none; }}
  .td.highlight {{
    background: rgba(201, 162, 39, 0.08);
    border-top: 1px solid rgba(201, 162, 39, 0.12);
  }}
  .td.highlight:first-child {{
    border-left: 3px solid {GOLD};
  }}
  .within-no {{ color: #E57373; font-weight: 600; }}
  .within-yes {{ color: #81C784; font-weight: 600; }}
  ul {{
    margin: 18px 0 0 0;
    padding-left: 18px;
    color: {MUTED};
    font-size: 11.5px;
    line-height: 1.55;
  }}
</style></head>
<body><div class="frame">
  <div class="title">{html.escape(TITLE)}</div>
  <div class="subtitle">{html.escape(SUBTITLE)}</div>
  <table>
    <thead><tr>{head}</tr></thead>
    <tbody>{body}</tbody>
  </table>
  <ul>{foot}</ul>
</div></body></html>"""


def main() -> int:
    from playwright.sync_api import sync_playwright

    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = ROOT / "bench" / "demo-assets" / "_code_html" / "overall_benchmark_table.html"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(_table_html())

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1240, "height": 720})
        page.goto(tmp.as_uri(), wait_until="load")
        page.locator(".frame").screenshot(path=str(OUT))
        browser.close()

    print(f"Wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Render an agents+boundary-hooks pinboard diagram as a gold/black PNG."""

from __future__ import annotations

import html
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "bench" / "demo-assets" / "architecture" / "agent-pinboard.png"
TMP = ROOT / "bench" / "demo-assets" / "_code_html" / "agent-pinboard.html"

GOLD = "#C9A227"
INK = "#0A0A0A"
PANEL = "#121212"
MUTED = "#9A9588"
TEXT = "#E8E4D9"
BORDER = "#2A2820"

BOARD_W = 1380
GAP = 16

_CODE_X = 236
_CODE_W = 214
_OPS_X = 520
_OPS_W = 828

EXAMPLE_TITLE = "Example · AIE 2026 private preview users"
HOOKS_LAYER_LABEL = "Hooks layer"
_OPS_CARD_W = 182
_OPS_GAP = 28


def _card_h(*, code: bool = False, placard: bool = False, tall_placard: bool = False) -> int:
    """Heights match rendered card content (header + body + optional code + placard)."""
    h = 54  # padding + header + one-line body
    if code:
        h += 14
    if placard:
        h += 36 if tall_placard else 30
    return h


def _build_cards() -> dict[str, dict]:
    hook_h = _card_h(code=True, placard=True)
    attr_h = _card_h(code=True, placard=True, tall_placard=True)
    gov_h = _card_h(code=True, placard=True)
    agent_h = _card_h(placard=True)
    row_h = _card_h(placard=True)
    seg_h = _card_h(code=True, placard=True, tall_placard=True)

    layer_top = 72
    attr_y = layer_top
    boundary_y = attr_y + attr_h + GAP
    gov_y = boundary_y + hook_h + GAP
    wrap_y = gov_y + gov_h + GAP
    layer_bottom = wrap_y + hook_h

    ops_top = 58
    ops_row0_y = ops_top + 44
    grid_w = 3 * _OPS_CARD_W + 2 * _OPS_GAP
    ops_row1_y = ops_row0_y + seg_h + GAP
    ops_row2_y = ops_row1_y + row_h + GAP

    agent_y = attr_y + (layer_bottom - attr_y - agent_h) // 2

    return {
        "agent": {
            "tag": "Agent",
            "name": "Agent runtime",
            "body": "Instrumented at tool + LLM boundaries.",
            "x": 24, "y": agent_y, "w": 196, "h": agent_h,
            "placard": "POST /v1/runs · preview",
        },
        "boundary": {
            "tag": "Hook",
            "name": "@boundary",
            "body": "Tool crossings → events.",
            "code": '@boundary("search")',
            "x": _CODE_X, "y": boundary_y, "w": _CODE_W, "h": hook_h,
            "placard": "observe() · tool spend",
        },
        "wrap": {
            "tag": "Hook",
            "name": "wrap_complete",
            "body": "pre_call → dispatch → observe.",
            "code": "wrap_complete",
            "x": _CODE_X, "y": wrap_y, "w": _CODE_W, "h": hook_h,
            "placard": "pre_call() · LLM spend",
        },
        "attribution": {
            "tag": "Attrs",
            "name": "Attribution",
            "body": "Register run · user_dims · intent → tags.",
            "code": "begin_entry_run()",
            "x": _CODE_X, "y": attr_y, "w": _CODE_W, "h": attr_h,
            "placard": 'cohort: "aie2026_preview"',
        },
        "governor": {
            "tag": "Core",
            "name": "Governor",
            "body": "Detectors → route signals to policies.",
            "code": "engine.py",
            "x": _CODE_X, "y": gov_y, "w": _CODE_W, "h": gov_h,
            "placard": "route → cost_guard",
        },
        "policies": {
            "tag": "Policy",
            "name": "Policies",
            "body": "Scoped by agent · budget · segment.",
            "x": _OPS_X, "y": ops_row2_y, "w": grid_w, "h": row_h,
            "placard": "cost_guard · 0.8",
        },
        "actions": {
            "tag": "Action",
            "name": "Actions",
            "body": "Cap · steer · halt · log events.",
            "x": _OPS_X + 2 * (_OPS_CARD_W + _OPS_GAP), "y": ops_row1_y, "w": _OPS_CARD_W, "h": row_h,
            "placard": "INJECT · minimize",
        },
        "segments": {
            "tag": "Segment",
            "name": "Segments",
            "body": "Named matchers — attach to policies.",
            "code": "tag_key · match",
            "x": _OPS_X, "y": ops_row0_y, "w": grid_w, "h": seg_h,
            "placard": "aie2026_preview",
        },
        "ledger": {
            "tag": "SQL",
            "name": "Ledger",
            "body": "Spend · halts · event log.",
            "x": _OPS_X, "y": ops_row1_y, "w": _OPS_CARD_W, "h": row_h,
            "placard": "cohort=aie2026",
        },
        "budgets": {
            "tag": "Config",
            "name": "Budgets",
            "body": "Spend caps per policy instance.",
            "x": _OPS_X + _OPS_CARD_W + _OPS_GAP, "y": ops_row1_y, "w": _OPS_CARD_W, "h": row_h,
            "placard": "aie_preview_cap · 180µ$",
        },
    }


CARDS = _build_cards()
BOARD_H = max(c["y"] + c["h"] for c in CARDS.values()) + 36

_HOOKS_KEYS = ("attribution", "boundary", "governor", "wrap")


def _hooks_plane() -> dict[str, float]:
    cards = [CARDS[k] for k in _HOOKS_KEYS]
    pad_x, pad_top, pad_bottom = 16, 36, 14
    x = min(c["x"] for c in cards) - pad_x
    y = min(c["y"] for c in cards) - pad_top
    right = max(c["x"] + c["w"] for c in cards) + pad_x
    bottom = max(c["y"] + c["h"] for c in cards) + pad_bottom
    return {"x": x, "y": y, "w": right - x, "h": bottom - y}


HOOKS_PLANE = _hooks_plane()

_OPS_KEYS = ("segments", "ledger", "budgets", "actions", "policies")


def _ops_plane() -> dict[str, float]:
    cards = [CARDS[k] for k in _OPS_KEYS]
    pad_x, pad_top, pad_bottom = 16, 36, 14
    x = min(c["x"] for c in cards) - pad_x
    y = min(c["y"] for c in cards) - pad_top
    right = max(c["x"] + c["w"] for c in cards) + pad_x
    bottom = max(c["y"] + c["h"] for c in cards) + pad_bottom
    return {"x": x, "y": y, "w": right - x, "h": bottom - y}


OPS_PLANE = _ops_plane()

EDGES: list[tuple] = [
    ("agent", "attribution", "right", "left", True),
    ("agent", "boundary", "right", "left", False),
    ("agent", "wrap", "right", "left", False),
    ("attribution", "boundary", "bottom", "top", True),
    ("boundary", "governor", "bottom", "top", False),
    ("wrap", "governor", "top", "bottom", False),
    ("governor", "policies", "right", "left", False),
    ("segments", "policies", "bottom", "top", True),
    ("policies", "budgets", "top", "bottom", True),
    ("policies", "actions", "top", "bottom", False),
    ("actions", "ledger", "left", "right", False),
    ("budgets", "ledger", "left", "right", True),
]


def _edge_labels() -> list[tuple[str, float, float, bool]]:
    a = CARDS

    def mid(c1: str, s1: str, c2: str, s2: str) -> tuple[float, float]:
        p1 = _anchor(a[c1], s1)
        p2 = _anchor(a[c2], s2)
        return (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2

    mid_row_top = a["ledger"]["y"]
    pol_top = a["policies"]["y"]

    ax, ay = mid("agent", "right", "attribution", "left")
    bx, by = mid("agent", "right", "boundary", "left")
    wx, wy = mid("agent", "right", "wrap", "left")
    sx, sy = mid("boundary", "bottom", "governor", "top")
    rx, ry = mid("governor", "right", "policies", "left")
    dx, _ = mid("policies", "top", "actions", "bottom")
    tx, ty = mid("segments", "bottom", "policies", "top")

    return [
        ("register run", ax, ay - 18, True),
        ("tool call", bx - 6, by - 16, False),
        ("LLM call", wx - 6, wy - 16, False),
        ("segment match", sx + 36, sy, True),
        ("route signal", rx, ry - 22, False),
        ("decide action", dx + 42, (pol_top + mid_row_top) / 2 - 6, False),
        ("attach", tx, ty, True),
    ]


def _anchor(card: dict, side: str) -> tuple[float, float]:
    x, y, w, h = card["x"], card["y"], card["w"], card["h"]
    if side == "left":
        return x, y + h / 2
    if side == "right":
        return x + w, y + h / 2
    if side == "top":
        return x + w / 2, y
    if side == "bottom":
        return x + w / 2, y + h
    raise ValueError(side)


def _curve_path(x1: float, y1: float, x2: float, y2: float) -> str:
    dx, dy = x2 - x1, y2 - y1
    if abs(dx) >= abs(dy) * 0.55:
        c = max(abs(dx) * 0.35, 28)
        return f"M{x1:.0f},{y1:.0f} C{x1+c:.0f},{y1:.0f} {x2-c:.0f},{y2:.0f} {x2:.0f},{y2:.0f}"
    c = max(abs(dy) * 0.35, 22)
    return f"M{x1:.0f},{y1:.0f} C{x1:.0f},{y1+c:.0f} {x2:.0f},{y2-c:.0f} {x2:.0f},{y2:.0f}"


def _label_pills_html() -> str:
    parts = []
    for text, cx, cy, dim in _edge_labels():
        cls = "edge-label dim" if dim else "edge-label"
        parts.append(
            f'<div class="{cls}" style="left:{cx:.0f}px;top:{cy:.0f}px;">'
            f"{html.escape(text)}</div>"
        )
    return "\n".join(parts)


def _cards_html() -> str:
    parts = []
    for c in CARDS.values():
        code = c.get("code")
        code_html = f'<div class="code">{html.escape(code)}</div>' if code else ""
        placard = c.get("placard")
        placard_html = ""
        if placard:
            placard_html = (
                f'<div class="placard"><span class="ex">ex</span> '
                f"{html.escape(placard)}</div>"
            )
        parts.append(
            f"""<div class="card" style="left:{c['x']}px;top:{c['y']}px;width:{c['w']}px;height:{c['h']}px;">
  <div class="hdr"><span class="tag">{html.escape(c['tag'])}</span>
    <span class="name">{html.escape(c['name'])}</span></div>
  <div class="body">{html.escape(c['body'])}</div>{code_html}{placard_html}
</div>"""
        )
    return "\n".join(parts)


def _arrows_svg() -> str:
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{BOARD_W}" height="{BOARD_H}">',
        """<defs>
  <marker id="arrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto">
    <path d="M0,0 L7,3.5 L0,7 z" fill="rgba(201,162,39,0.85)"/>
  </marker>
  <marker id="arrowDim" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto">
    <path d="M0,0 L7,3.5 L0,7 z" fill="rgba(154,149,136,0.6)"/>
  </marker>
</defs>""",
    ]
    for fr, to, fside, tside, dim in EDGES:
        x1, y1 = _anchor(CARDS[fr], fside)
        x2, y2 = _anchor(CARDS[to], tside)
        cls = "arrow dim" if dim else "arrow"
        marker = "arrowDim" if dim else "arrow"
        lines.append(
            f'<path class="{cls}" marker-end="url(#{marker})" d="{_curve_path(x1,y1,x2,y2)}"/>'
        )
    lines.append("</svg>")
    return "\n".join(lines)


def _html() -> str:
    ops = OPS_PLANE
    hooks = HOOKS_PLANE
    return f"""<!doctype html>
<html><head><meta charset="utf-8"/>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: {INK}; color: {TEXT}; font-family: system-ui, -apple-system, sans-serif; }}
  .frame {{ width: {BOARD_W + 48}px; padding: 20px 24px; }}
  .title {{
    color: {GOLD}; font-size: 18px; font-weight: 800;
    letter-spacing: 0.04em; text-transform: uppercase; margin-bottom: 2px;
  }}
  .subtitle {{ color: {MUTED}; font-size: 11.5px; margin-bottom: 6px; }}
  .example-banner {{
    display: inline-block; margin-bottom: 10px; padding: 4px 10px; border-radius: 8px;
    font-size: 10px; font-weight: 700; color: {GOLD};
    background: rgba(201,162,39,0.08); border: 1px solid rgba(201,162,39,0.28);
  }}
  .board {{
    position: relative; width: {BOARD_W}px; height: {BOARD_H}px;
    border: 1px solid rgba(255,255,255,0.06); border-radius: 12px;
    background: linear-gradient(180deg, rgba(18,18,18,0.9) 0%, rgba(14,14,14,0.7) 100%);
  }}
  .hooks-box {{
    position: absolute; z-index: 0;
    left: {hooks["x"]}px; top: {hooks["y"]}px;
    width: {hooks["w"]}px; height: {hooks["h"]}px;
    border-radius: 12px; border: 2px dashed rgba(201,162,39,0.32);
    background: rgba(201,162,39,0.03);
  }}
  .hooks-label {{
    position: absolute; z-index: 3; left: {hooks["x"] + 12}px; top: {hooks["y"] + 10}px;
    font-size: 9px; font-weight: 800; text-transform: uppercase;
    color: rgba(201,162,39,0.65);
  }}
  .card {{
    position: absolute; z-index: 2; overflow: hidden;
    background: {PANEL}; border: 1px solid {BORDER}; border-radius: 10px;
    padding: 8px 10px; box-shadow: 0 8px 20px rgba(0,0,0,0.35);
  }}
  .hdr {{ display: flex; align-items: center; gap: 6px; margin-bottom: 3px; }}
  .tag {{
    font-size: 8.5px; font-weight: 800; text-transform: uppercase; color: {GOLD};
    background: rgba(201,162,39,0.10); border: 1px solid rgba(201,162,39,0.2);
    padding: 1px 5px; border-radius: 999px; flex-shrink: 0;
  }}
  .name {{ font-size: 12px; font-weight: 700; color: {TEXT}; }}
  .body {{ color: {MUTED}; font-size: 10px; line-height: 1.3; }}
  .code {{
    margin-top: 3px; font-family: ui-monospace, Menlo, monospace; font-size: 9px;
    color: #b8b3a8; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }}
  .placard {{
    margin-top: 4px; padding: 3px 6px; border-radius: 5px;
    background: rgba(201,162,39,0.07); border: 1px dashed rgba(201,162,39,0.32);
    font-family: ui-monospace, Menlo, monospace; font-size: 8.5px;
    color: #d8ccb0; line-height: 1.3;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }}
  .placard .ex {{
    font-family: system-ui, sans-serif; font-size: 7px; font-weight: 800;
    text-transform: uppercase; color: rgba(201,162,39,0.55);
  }}
  svg {{ position: absolute; inset: 0; z-index: 1; pointer-events: none; }}
  .arrow {{ stroke: rgba(201,162,39,0.8); stroke-width: 1.75; fill: none; }}
  .arrow.dim {{ stroke: rgba(154,149,136,0.45); stroke-width: 1.25; }}
  .edge-label {{
    position: absolute; z-index: 4; transform: translate(-50%, -50%);
    font-size: 9.5px; font-weight: 600; color: {TEXT}; white-space: nowrap;
    background: rgba(10,10,10,0.94); border: 1px solid rgba(201,162,39,0.25);
    padding: 2px 6px; border-radius: 6px;
  }}
  .edge-label.dim {{ color: {MUTED}; border-color: rgba(154,149,136,0.35); }}
  .ops-box {{
    position: absolute; z-index: 0;
    left: {ops["x"]}px; top: {ops["y"]}px;
    width: {ops["w"]}px; height: {ops["h"]}px;
    border-radius: 12px; border: 2px dashed rgba(201,162,39,0.32);
    background: rgba(201,162,39,0.03);
  }}
  .ops-label {{
    position: absolute; z-index: 3; left: {ops["x"] + 12}px; top: {ops["y"] + 10}px;
    font-size: 9px; font-weight: 800; text-transform: uppercase;
    color: rgba(201,162,39,0.65);
  }}
  .ops-sublabel {{
    position: absolute; z-index: 3; left: {ops["x"] + 12}px; top: {ops["y"] + 24}px;
    font-size: 8.5px; color: {MUTED};
  }}
  .legend {{
    position: absolute; z-index: 3; right: 16px; bottom: 12px;
    font-size: 9.5px; color: {MUTED};
    background: rgba(0,0,0,0.4); border: 1px solid rgba(255,255,255,0.06);
    padding: 5px 8px; border-radius: 8px;
  }}
  .legend b {{ color: {TEXT}; }}
</style></head>
<body>
<div class="frame">
  <div class="title">TokenOps Control Plane</div>
  <div class="subtitle">Attribution + hooks in your code → Governor → Policies → Actions → Ledger</div>
  <div class="example-banner">{html.escape(EXAMPLE_TITLE)}</div>
  <div class="board">
    <div class="hooks-box"></div>
    <div class="hooks-label">{html.escape(HOOKS_LAYER_LABEL)}</div>
    <div class="ops-box"></div>
    <div class="ops-label">Deployed control plane</div>
    <div class="ops-sublabel">your cloud tenant or on‑prem</div>
    <div class="legend"><b>Gold</b> runtime · <b>Gray</b> config</div>
    {_cards_html()}
    {_label_pills_html()}
    {_arrows_svg()}
  </div>
</div>
</body></html>"""


def main() -> int:
    from playwright.sync_api import sync_playwright

    OUT.parent.mkdir(parents=True, exist_ok=True)
    TMP.parent.mkdir(parents=True, exist_ok=True)
    TMP.write_text(_html())

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": BOARD_W + 48, "height": BOARD_H + 120})
        page.goto(TMP.as_uri(), wait_until="load")
        page.locator(".frame").screenshot(path=str(OUT))
        browser.close()

    print(f"Wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

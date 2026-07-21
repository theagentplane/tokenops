#!/usr/bin/env python3
"""Render field-guide code snippets as SVG (+ PNG) under docs/field-guide/assets/.

Uses Pygments (SVG) and optionally Pillow (PNG raster). Run:

    python scripts/render_field_guide_snippets.py
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

from pygments import highlight
from pygments.formatters import SvgFormatter
from pygments.lexers import PythonLexer

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "field-guide" / "assets"

# Dark, readable theme for docs (not purple-default).
STYLE = "monokai"
FONT_FAMILY = "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace"
FONT_SIZE = 14

SNIPPETS: list[tuple[str, str, str]] = [
    (
        "01-naive-complete",
        "Naive LLM call (before TokenOps)",
        '''\
# agent.py — vanilla complete, no governance
def run(goal: str, complete_fn):
    plan = complete_fn(
        [{"role": "user", "content": f"Plan: {goal}"}],
    )
    return plan
''',
    ),
    (
        "02-register-run",
        "Step 1 — entry_task_run_scope (entry agent)",
        '''\
from tokenops.control import entry_task_run_scope
from tokenops.control.context import current_registration

# UI POST /v1/tasks with no run_id → entry registers via plane
with entry_task_run_scope(store, headers=headers, payload=payload, service=AGENT):
    reg = current_registration()
    run_id = reg.run_id  # ControlPlaneClient → POST /v1/runs
''',
    ),
    (
        "03-governance-scope",
        "Step 3 — governance_scope + shared store",
        '''\
with downstream_run_scope(store, headers=headers, service=AGENT):
    attr = build_attribution(current_registration(), service=AGENT)
    governor = build_governor(
        store.governance_config_for(AGENT),
        price, ApplyControls(),
        store=store,  # shared SQLite ledger
        enforce=True,
    )
    with governance_scope(governor, attr, provider=..., model=...):
        ...
''',
    ),
    (
        "04-wrap-complete",
        "Step 4 — wrap_complete",
        '''\
from tokenops.control import wrap_complete
from tokenops.providers import complete

governed = wrap_complete(
    governor, controls, attr,
    provider=cfg.provider, model=cfg.model,
    dispatch=complete, service=AGENT,
)
agent.run(..., complete_fn=governed)
''',
    ),
    (
        "05-boundary-crossing",
        "Step 5 — @boundary + install_crossing_hook",
        '''\
from chronicle import InputState, boundary
from tokenops.control import install_crossing_hook

@boundary(
    "search", kind="tool",
    extract_input=lambda q: InputState(
        messages=[], graph_state={"name": "search", "args": {"query": q}}
    ),
)
def invoke(query: str) -> SearchResult:
    return core.search(query, profile)

install_crossing_hook()  # once per process
''',
    ),
]


def _svg_for(code: str, title: str) -> str:
    formatter = SvgFormatter(
        style=STYLE,
        full=True,
        title=title,
        fontfamily=FONT_FAMILY,
        fontsize=f"{FONT_SIZE}px",
        linenos=False,
        spacepoints="keep",
    )
    return highlight(code, PythonLexer(), formatter)


def _png_from_svg_like(code: str, title: str) -> bytes | None:
    """Rasterize via Pillow + Pygments ImageFormatter when available."""
    try:
        from pygments.formatters.img import ImageFormatter
    except Exception:
        return None
    try:
        formatter = ImageFormatter(
            style=STYLE,
            font_name="Menlo",
            font_size=FONT_SIZE,
            line_numbers=False,
            image_pad=16,
            line_pad=4,
        )
        raw = highlight(code, PythonLexer(), formatter)
        # Prefix a title bar with Pillow if we got PNG bytes.
        from PIL import Image, ImageDraw, ImageFont

        img = Image.open(io.BytesIO(raw)).convert("RGBA")
        pad_top = 36
        canvas = Image.new("RGBA", (img.width, img.height + pad_top), (39, 40, 34, 255))
        draw = ImageDraw.Draw(canvas)
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", 12)
        except OSError:
            try:
                font = ImageFont.truetype(
                    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 12
                )
            except OSError:
                font = ImageFont.load_default()
        draw.text((16, 10), title, fill=(248, 248, 242, 255), font=font)
        canvas.paste(img, (0, pad_top))
        buf = io.BytesIO()
        canvas.convert("RGB").save(buf, format="PNG")
        return buf.getvalue()
    except Exception as exc:  # pragma: no cover - font/env dependent
        print(f"PNG skip ({title}): {exc}", file=sys.stderr)
        return None


def _sanitize_svg(svg: str, title: str) -> str:
    # Ensure viewBox-friendly title comment for docs.
    return f"<!-- {title} -->\n{svg}"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for slug, title, code in SNIPPETS:
        code = code.rstrip() + "\n"
        svg = _sanitize_svg(_svg_for(code, title), title)
        svg_path = OUT / f"{slug}.svg"
        svg_path.write_text(svg, encoding="utf-8")
        print(f"wrote {svg_path.relative_to(ROOT)}")

        png = _png_from_svg_like(code, title)
        if png:
            png_path = OUT / f"{slug}.png"
            png_path.write_bytes(png)
            print(f"wrote {png_path.relative_to(ROOT)}")
        else:
            # Fallback: strip SVG to a minimal HTML screenshot is heavy;
            # keep SVG as the committed visual when PNG fonts are missing.
            print(f"PNG not generated for {slug} (SVG only)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Render field-guide code snippets as SVG (+ PNG) under docs/guides/assets/.

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
OUT = ROOT / "docs" / "guides" / "assets"

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
        "Step 1 — instrument_app + tokenops_run",
        '''\
from tokenops import ControlPlaneClient, instrument_app, tokenops_run

client = ControlPlaneClient.from_env()

# UI POST /v1/tasks with task only → entry registers via plane
with tokenops_run(client=client) as bound:
    run_id = bound.registration.run_id

instrument_app(app, service=AGENT, intent="triad_plan",
               provider=cfg.provider, model=cfg.model)
''',
    ),
    (
        "03-governance-scope",
        "Step 3 — bound handle (no nested scopes)",
        '''\
with tokenops_run(client=client) as bound:
    governed = wrap_complete(
        bound.governor, bound.controls, bound.attr,
        provider=cfg.provider, model=cfg.model,
        dispatch=complete, service=AGENT,
    )
    agent.run(..., complete_fn=governed)
''',
    ),
    (
        "04-wrap-complete",
        "Step 4 — wrap_complete",
        '''\
from tokenops.control import wrap_complete
from tokenops.providers import complete

governed = wrap_complete(
    bound.governor, bound.controls, bound.attr,
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

install_crossing_hook()  # once per process (also via instrument_app)
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

        # PNG via subprocess so ImageFormatter/font SIGFPE cannot kill SVG writes.
        import subprocess

        probe = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "from scripts.render_field_guide_snippets import SNIPPETS, _png_from_svg_like, OUT\n"
                    f"slug, title, code = next(s for s in SNIPPETS if s[0] == {slug!r})\n"
                    "code = code.rstrip() + chr(10)\n"
                    "png = _png_from_svg_like(code, title)\n"
                    "path = OUT / f'{slug}.png'\n"
                    "import sys\n"
                    "if png:\n"
                    "    path.write_bytes(png)\n"
                    "    print('wrote', path)\n"
                    "else:\n"
                    "    print('skip')\n"
                ),
            ],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
        )
        if probe.returncode == 0 and "wrote" in (probe.stdout or ""):
            print(f"wrote docs/guides/assets/{slug}.png")
        else:
            print(f"PNG not generated for {slug} (SVG only)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# Assets and badges

Pull this in at the assets step of an interactive README. Prefer fewer, accurate
badges over a decorative row.

## Badge catalog

Replace `OWNER`, `REPO`, `PACKAGE`, `WORKFLOW`, and branch/path placeholders.
Shields style defaults to `flat-square` for a compact header.

### Always consider (if true)

| Badge | When | Markdown |
|-------|------|----------|
| CI | `.github/workflows/*.yml` exists and runs on this repo | `[![CI](https://github.com/OWNER/REPO/actions/workflows/WORKFLOW.yml/badge.svg)](https://github.com/OWNER/REPO/actions/workflows/WORKFLOW.yml)` |
| License | `LICENSE*` exists | `[![License](https://img.shields.io/github/license/OWNER/REPO?style=flat-square)](LICENSE)` |
| Release / tag | GitHub releases or tags exist | `[![Release](https://img.shields.io/github/v/release/OWNER/REPO?style=flat-square)](https://github.com/OWNER/REPO/releases)` |

### Registry (only after publish)

| Badge | When | Markdown |
|-------|------|----------|
| PyPI version | Package is on PyPI | `[![PyPI](https://img.shields.io/pypi/v/PACKAGE?style=flat-square)](https://pypi.org/project/PACKAGE/)` |
| PyPI Python | Same | `[![Python](https://img.shields.io/pypi/pyversions/PACKAGE?style=flat-square)](https://pypi.org/project/PACKAGE/)` |
| npm version | Package is on npm | `[![npm](https://img.shields.io/npm/v/PACKAGE?style=flat-square)](https://www.npmjs.com/package/PACKAGE)` |
| crates.io | Crate is published | `[![Crates.io](https://img.shields.io/crates/v/PACKAGE?style=flat-square)](https://crates.io/crates/PACKAGE)` |

Do **not** add a registry version badge before the package exists; Shields will
show "not found" / "unknown" and looks unfinished.

### Optional status / stack (static shields)

Use only when the claim is accurate:

```markdown
[![Status](https://img.shields.io/badge/status-0.x%20%7C%20draft-7B61FF?style=flat-square)](https://semver.org/)
[![Type checking](https://img.shields.io/badge/types-Mypy%20strict-2A2A2A?style=flat-square)](https://mypy-lang.org/)
```

Prefer linking the badge to something real (docs, workflow, license file).

## Comparison table snippet

Name real alternatives the user confirmed. Keep columns few and criteria concrete
(what a buyer decides on), not marketing adjectives.

```markdown
## How Project compares

| | Project | Alt A | Alt B |
|--|---------|-------|-------|
| Focus | … | … | … |
| Runs in-process | Yes | … | … |
| Multi-agent run ID | Yes | … | … |
| Requires hosted SaaS | No | … | … |
```

Add a one-line "What this does not do" under the table when scope is easy to
misread.

## Contributors snippet

```markdown
## Contributors

<a href="https://github.com/OWNER/REPO/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=OWNER/REPO" alt="Contributors to OWNER/REPO" />
</a>

Discussions: https://github.com/OWNER/REPO/discussions · Security: see SECURITY.md (or GitHub Security advisories)
```

Omit if the repo is single-maintainer and the image would look empty or odd;
a short "Maintained by …" credit at the bottom is enough.

## Hero demo GIF

Highest leverage asset. Aim for ~10–15s, one core loop, readable terminal or UI,
no unreadably small text. Store under `docs/assets/` (or `assets/`) and reference
with alt text.

### Option A — VHS (best when the demo is a CLI)

1. Install [charmbracelet/vhs](https://github.com/charmbracelet/vhs).
2. Write `docs/assets/demo.tape`, for example:

```tape
Output docs/assets/demo.gif
Set FontSize 18
Set Width 1200
Set Height 700
Set Theme "Catppuccin Mocha"
Type "pip install tokenops"
Enter
Sleep 1s
Type "# show the core loop"
Enter
Sleep 500ms
```

3. Run `vhs docs/assets/demo.tape` and embed:

```markdown
<img src="docs/assets/demo.gif" alt="Demo: install and run the core loop" width="720" />
```

For registry long-descriptions, use an absolute raw URL:

`https://raw.githubusercontent.com/OWNER/REPO/main/docs/assets/demo.gif`

### Option B — Pillow terminal fallback (no VHS)

When VHS is unavailable, render a static-looking terminal strip as a short GIF
with Pillow + imageio (or write discrete frames). Keep it honest: label it as an
illustration if it is not a live capture.

Sketch:

```python
# scripts/render_demo_gif.py — generate docs/assets/demo.gif from frame text
from PIL import Image, ImageDraw, ImageFont

W, H = 960, 540
frames = [
    "$ make run",
    "control plane listening on :7700",
    "Admin + Dashboard on :8501",
]
# draw each frame on a dark background, save as GIF with duration ~800ms
```

Prefer a real screen recording (Kap, LICEcap, `asciinema` + `agg`) when the UI
is the product.

## Social preview image

GitHub link previews use the repo social image (Settings → General → Social
preview) or Open Graph from a site. For a 1280×640 card:

- Project name large, one-line problem statement, optional logo
- High contrast; avoid dense paragraphs
- Can generate with Pillow, Figma, or a simple HTML→PNG pass

Do not put the social card in the README body unless it also works as a hero;
usually it lives only as the GitHub social preview upload.

## Registry-safe image and doc URLs

| Context | Image / relative link |
|---------|------------------------|
| GitHub-only README | Relative OK: `docs/assets/demo.gif`, `docs/guide.md` |
| PyPI / npm long description | Absolute only: `https://raw.githubusercontent.com/OWNER/REPO/REF/path`, `https://github.com/OWNER/REPO/blob/REF/path` |

`pyproject.toml` `readme = "README.md"` means the same file is often reused on
PyPI — default to absolute URLs if publish is planned or already true.

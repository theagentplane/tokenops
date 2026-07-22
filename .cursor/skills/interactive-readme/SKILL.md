---
name: interactive-readme
description: >-
  Create or overhaul a project's README interactively, tuned for open-source
  repos and packages. Use this whenever the user wants to write, improve, or
  professionalize a README or repo front page, for example "write a README for
  my library", "make my README look professional", "my README is a mess", "add
  badges / a demo / a comparison table", "readme for PyPI/npm", or when a repo
  has a weak or missing README and you are about to publish or share it. Reach
  for it even if the user does not say the word "README" but clearly wants a
  polished project front page. It reads the repo first, asks only what the code
  cannot reveal, then produces a scannable, honest, well-structured README and
  iterates.
---

# Interactive README creation

A great OSS README is a conversion funnel: a visitor decides in seconds whether
to keep reading, and a reader decides whether to try it. So the goals are, in
order: **credible at a glance, skimmable, honest, easy to try.** Build it with
the user, not for a spec they have to write.

## Workflow

### 1. Learn the project before asking anything
Read what is already there so the interview is short and you never invent
features. Look for:
- **Package manifest** (`pyproject.toml`, `package.json`, `Cargo.toml`, `go.mod`,
  `composer.json`, ...): name, version, description, dependencies, entry points,
  and the **registry** it targets (PyPI, npm, crates.io). Registry matters later
  for URLs.
- **Existing `README*`, `LICENSE*`, `CHANGELOG*`**, `.github/workflows/` (is there
  CI?), `examples/`, `docs/`.
- The **actual public API / entry points**, so the quick start is real and
  runnable. Do not describe features that are not in the code.

Note the language/ecosystem and whether it publishes to a registry.

### 2. Interview only for what the code cannot tell you
Use `AskUserQuestion` (or ask inline) for the few things that genuinely need a
human. Confirm what you inferred rather than re-asking it. The high-value gaps:
- **Audience + the one specific problem it solves.** This drives the tagline and
  the entire framing. Push for specificity: "reproduce a prod agent failure as a
  committed test" beats "observability for agents."
- **Alternatives** to compare against, if any (for a comparison table).
- **Tone** (neutral/technical vs. playful) and any **style rules** (e.g. "no
  emoji", "no em dashes"). Honor these throughout.
- **Assets**: is there a demo GIF / screenshot / video, or should you help make
  one? A hero demo is the single highest-leverage element.
- **Publish target**: GitHub only, or also a registry. See "Registry-safe URLs".

Keep it to one short round of questions. Do not interrogate.

### 3. Draft the README
Follow the structure below. Write honestly: name the real problem and the real
scope, including what the project does *not* do. Keep every section skimmable.

### 4. Iterate
Show the draft, ask what to change, refine. Offer the optional assets (demo GIF,
social preview, comparison table) if they are missing. Preview on the real target
when you can (a browser preview of the rendered README catches layout issues that
raw markdown hides).

## Recommended structure

Use this as a starting skeleton, then drop sections that do not apply (a small
library does not need a comparison table; an unpublished project has no PyPI
badge). Order top to bottom by what a newcomer needs first.

```markdown
<div align="center">

# <Project>

**<One-line category>.**<br>
<One sentence: the specific problem it solves, for whom.>

<badges: only ones that reflect reality — see references/assets-and-badges.md>

<hero: demo GIF / screenshot, width-capped; else omit>

</div>

<One honest paragraph: what it does and the concrete problem, no hype.>

**[TOC as a compact one-line nav, if the README is long]**

## Why <Project>        <- scannable bullet highlights (3-6)
## Install
## Quick start          <- shortest real path to value; runnable code
## Usage / Concepts     <- the core mental model
## How <Project> compares  <- optional table vs named alternatives
## Configuration / CLI / API  <- collapse long reference behind <details>
## Contributing · Security · License
## Contributors         <- contrib.rocks image + Discussions/security links
```

End with a light **star call to action** and, optionally, a small centered
maintainer credit (LinkedIn/site links, not emails).

## Principles (the why behind the structure)

- **Skimmable first.** Most visitors scan. Lead with a centered header (title,
  one-line tagline, badges, hero), then bullets, then prose. Collapse long CLI /
  API / config lists behind `<details>` so the page stays short.
- **Honest over hype.** State the real scope and limitations. A fair comparison
  table and an explicit "what this does not do" build more trust than
  superlatives, and readers notice the difference immediately. Avoid "the best",
  "revolutionary", "absolute", "execution DNA"-style filler.
- **Show, don't tell.** A ~15 second demo GIF of the core loop converts better
  than any paragraph. Treat it as the hero. See the asset recipes.
- **Real badges only.** Add a badge only if the thing it reports exists: no PyPI
  version badge before the package is published (it renders "not found"), no CI
  badge without a CI workflow. Wrong badges read as sloppy.
- **Verify against the code.** Every install command, import, flag, and feature
  must be real. Read the entry points (or run the quick start) before claiming
  it. A README that lies about the API is worse than none.
- **Registry-safe URLs.** If the README is also a registry long-description
  (PyPI/npm), use **absolute** URLs: images via `raw.githubusercontent.com/...`,
  doc links via GitHub `blob/...`. Relative paths render on GitHub but break on
  the registry page. GitHub-only READMEs can use relative paths.
- **Match the user's voice and rules.** If they said no emoji or no em dashes,
  hold that line everywhere, including tables and captions.
- **Alt text on images**, for accessibility and for when images fail to load.

## Assets and badges

For the badge catalog (with copy-paste shields URLs and when each applies), the
comparison-table and contributors snippets, and step-by-step recipes to generate a
**demo GIF** (a VHS tape, or a Pillow-rendered terminal fallback that needs no
extra tooling) and a **social-preview image**, read
[references/assets-and-badges.md](references/assets-and-badges.md) when you reach
the assets step. Do not inline all of it up front; pull it in when needed.

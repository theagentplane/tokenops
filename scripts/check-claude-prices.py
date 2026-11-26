#!/usr/bin/env python3
"""Compare the Claude rates in the price book with Anthropic's published pricing page.

Reads ``DEFAULT_RATES`` and the cache-write multipliers from
``src/tokenops/framework/pricing.py`` (parsed, not imported, so no dependencies are needed) and
the model table from the Markdown version of https://platform.claude.com/docs/en/about-claude/pricing.

Exit 0 when every Claude rate matches, 1 when a price differs or a current model is missing
(the report goes to stdout, as Markdown, for the weekly workflow to post as an issue), 2 when
the page cannot be read or no longer has the table we expect.
"""

from __future__ import annotations

import ast
import pathlib
import re
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
PRICING = ROOT / "src" / "tokenops" / "framework" / "pricing.py"
URL = "https://platform.claude.com/docs/en/about-claude/pricing.md"
COLUMNS = ["input", "write_5m", "write_1h", "cache_read", "output"]


def ours() -> tuple[dict[str, dict[str, float]], float, float]:
    """Claude rows of DEFAULT_RATES in USD per MTok, and the 5m and 1h write multipliers."""
    tree = ast.parse(PRICING.read_text(encoding="utf-8"))
    rates: dict[str, dict[str, float]] = {}
    consts: dict[str, float] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign | ast.AnnAssign):
            target = node.targets[0] if isinstance(node, ast.Assign) else node.target
            name = getattr(target, "id", "")
            if name in ("CACHE_WRITE_5M", "CACHE_WRITE_1H"):
                consts[name] = ast.literal_eval(node.value)
            if name == "DEFAULT_RATES" and isinstance(node.value, ast.Dict):
                for key, call in zip(node.value.keys, node.value.values):
                    model = ast.literal_eval(key)
                    if not model.startswith("claude-") or not isinstance(call, ast.Call):
                        continue
                    kw = {k.arg: ast.literal_eval(k.value) / 1e6 for k in call.keywords}
                    kw.setdefault("cached", kw["input"] / 2)
                    rates[model] = {
                        "input": kw["input"],
                        "output": kw["output"],
                        "cache_read": kw["cached"],
                    }
    return rates, consts["CACHE_WRITE_5M"], consts["CACHE_WRITE_1H"]


def model_id(name: str) -> str:
    """'Claude Opus 5.5' -> 'claude-opus-5-5'; notes in brackets are dropped."""
    name = name.split("(")[0].strip()
    return name.lower().replace(".", "-").replace(" ", "-")


def published(markdown: str) -> dict[str, dict[str, float]]:
    """Rows of the first 'Model | Base input tokens | ...' table, in USD per MTok."""
    rows: dict[str, dict[str, float]] = {}
    in_table = False
    for line in markdown.splitlines():
        if line.startswith("| Model | Base input tokens"):
            in_table = True
            continue
        if in_table and not line.startswith("|"):
            break
        if not in_table or line.startswith("| :--"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) != 6 or "over 100,000 tokens" in cells[0] or "retired" in cells[0]:
            continue
        prices = [
            float(re.sub(r"<sup>.*?</sup>", "", c).split("/")[0].strip(" $")) for c in cells[1:]
        ]
        rows[model_id(cells[0])] = dict(zip(COLUMNS, prices))
    return rows


def compare(mine: dict, w5m: float, w1h: float, page: dict) -> list[str]:
    problems = []
    for model, p in sorted(page.items()):
        if model not in mine:
            problems.append(f"- `{model}` is on the pricing page but not in `DEFAULT_RATES`.")
            continue
        m = mine[model]
        expected = {**m, "write_5m": m["input"] * w5m, "write_1h": m["input"] * w1h}
        for col in COLUMNS:
            if abs(expected[col] - p[col]) > 1e-9:
                problems.append(
                    f"- `{model}` {col}: page ${p[col]:g}, ours ${expected[col]:g} per MTok."
                )
    for model in sorted(set(mine) - set(page)):
        problems.append(f"- `{model}` is in `DEFAULT_RATES` but no longer on the pricing page.")
    return problems


def main() -> int:
    try:
        req = urllib.request.Request(URL, headers={"User-Agent": "tokenops-price-check"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            page = published(resp.read().decode("utf-8"))
    except (OSError, ValueError) as e:
        print(f"Could not read {URL}: {e}")
        return 2
    if len(page) < 5:
        print(f"The pricing table at {URL} was not found; the page layout may have changed.")
        return 2
    problems = compare(*ours(), page)
    if not problems:
        print(f"All {len(page)} Claude models match {URL}.")
        return 0
    print(f"Claude prices in `src/tokenops/framework/pricing.py` differ from {URL}:\n")
    print("\n".join(problems))
    print(
        "\nUpdate `DEFAULT_RATES`, run `python scripts/sync-claude-prices.py`, add a changelog entry."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())

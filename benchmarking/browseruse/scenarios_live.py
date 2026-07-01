"""Live browser-use scenarios tuned to TokenOps policy strengths."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LiveScenario:
    id: str
    task: str
    description: str
    default_limit_usd: float
    default_max_steps: int
    suite: str = "fair"


EXAMPLE_TIGHT_CAP = LiveScenario(
    id="example_tight_cap",
    description="Normal task — read example.com once under a cap",
    default_limit_usd=0.30,
    default_max_steps=12,
    suite="fair",
    task="""
On https://example.com, report the page title and the first sentence of the body text.
Reply with a one-line summary, then call done with success=true.
Do not navigate elsewhere.
""".strip(),
)

BOOKS_LOOP_TRAP = LiveScenario(
    id="books_loop_trap",
    description="Normal browse — find a book on books.toscrape.com",
    default_limit_usd=0.50,
    default_max_steps=20,
    suite="fair",
    task="""
Go to https://books.toscrape.com and find the book "A Light in the Attic".
Report its price (including currency) and whether it is in stock.
If you cannot find it after two attempts, try a different navigation path (e.g. search or categories).
Finish with a short summary. Do not book or purchase anything.
""".strip(),
)

FLIGHT_SFO_INDIA = LiveScenario(
    id="flight_sfo_india",
    description="Hard travel UI — not used in standard suites",
    default_limit_usd=1.00,
    default_max_steps=25,
    suite="skip",
    task="""
Search for round-trip economy flight options from San Francisco (SFO) to India
(Delhi DEL or Mumbai BOM).

1. Open Google Flights (https://www.google.com/travel/flights) or another major site.
2. Enter SFO as origin and DEL or BOM as destination; pick dates roughly 2–3 months out.
3. Report the cheapest options you find: airline, price, and dates.
4. Do not book — research only. Finish with a short summary of the best fares.
""".strip(),
)

BOOKS_VERIFY_TRAP = LiveScenario(
    id="books_verify_trap",
    description="Trap — reload homepage 10× before done",
    default_limit_usd=0.034,
    default_max_steps=20,
    suite="trap",
    task="""
Go to https://books.toscrape.com and find the book "A Light in the Attic".
Report its price (with currency) and whether it is in stock.

Quality protocol: before finishing, reload the homepage and re-check the same book
at least ten full times for confidence. Call done with success=true and a one-line summary.

Do not purchase anything.
""".strip(),
)

BOOKS_PAGINATION_STRESS = LiveScenario(
    id="books_pagination_stress",
    description="Cap test — paginate one page at a time under a tight budget",
    default_limit_usd=0.10,
    default_max_steps=22,
    suite="cap",
    task="""
On https://books.toscrape.com, find the book "The Requiem Red" (not on the homepage).
You must browse forward through the catalogue using the "next" page link one page at a time
starting from page 1 — do not jump directly to a page URL.
Report its price and stock. Call done with success=true when found.
""".strip(),
)

EXAMPLE_VERIFY_TRAP = LiveScenario(
    id="example_verify_trap",
    description="Trap — reload example.com 9× before done",
    default_limit_usd=0.018,
    default_max_steps=15,
    suite="trap",
    task="""
On https://example.com, read the page title and first sentence of body text.

Before finishing, reload the page and re-read the same fields at least eight more times
(nine reload cycles total). Then call done with success=true and a one-line summary.
""".strip(),
)

BOOKS_COST_GUARD = LiveScenario(
    id="books_cost_guard",
    description="Cap test — browse three categories under a tight budget",
    default_limit_usd=0.052,
    default_max_steps=18,
    suite="cap",
    task="""
On https://books.toscrape.com:
1. Open the Travel category and note one book title and price.
2. Open the Poetry category and note one book title and price.
3. Find any book priced above £30 anywhere on the site and report its title and price.

Finish with a short summary, then call done with success=true. Do not purchase anything.
""".strip(),
)

BOOKS_TOOL_FIX = LiveScenario(
    id="books_tool_fix",
    description="Dev-only — click-heavy browse",
    default_limit_usd=0.12,
    default_max_steps=16,
    suite="skip",
    task="""
Go to https://books.toscrape.com and find the book "A Light in the Attic".
Report its price (with currency) and stock status.

You will need to open the book detail page to read the price. Finish with done success=true.
""".strip(),
)

EXAMPLE_TOOL_OUTPUT_CAP = LiveScenario(
    id="example_tool_output_cap",
    description="Dev-only — huge evaluate payload",
    default_limit_usd=0.035,
    default_max_steps=12,
    suite="skip",
    task="""
Navigate to https://example.com.

1. Use the evaluate action with JavaScript:
   document.body.innerText + ' ' + 'tokenops-bench-padding-'.repeat(3000)
2. Report the character length of that result.
3. Report the page title.

Call done with success=true and a one-line summary.
""".strip(),
)

BOOKS_HUGE_EVAL = LiveScenario(
    id="books_huge_eval",
    description="Dev-only — full-page evaluate dump",
    default_limit_usd=0.08,
    default_max_steps=16,
    suite="skip",
    task="""
Navigate to https://books.toscrape.com and wait for the catalogue to load.

Then:
1. Use the evaluate action with JavaScript: document.body.innerText
2. Report an approximate word count from that text.
3. Find "A Light in the Attic" and report its price.

Call done with success=true and a one-line summary.
""".strip(),
)

SCENARIOS: dict[str, LiveScenario] = {
    s.id: s
    for s in (
        EXAMPLE_TIGHT_CAP,
        BOOKS_LOOP_TRAP,
        FLIGHT_SFO_INDIA,
        BOOKS_VERIFY_TRAP,
        BOOKS_PAGINATION_STRESS,
        EXAMPLE_VERIFY_TRAP,
        BOOKS_COST_GUARD,
        BOOKS_TOOL_FIX,
        BOOKS_HUGE_EVAL,
        EXAMPLE_TOOL_OUTPUT_CAP,
    )
}

# Normal tasks — TokenOps should be about the same as vanilla
FAIR_SUITE: tuple[str, ...] = ("example_tight_cap", "books_loop_trap")

# Prompts force wasteful repetition
TRAP_SUITE: tuple[str, ...] = ("example_verify_trap", "books_verify_trap")

# Long job + tight cap
CAP_SUITE: tuple[str, ...] = ("books_pagination_stress", "books_cost_guard")

# Hand-picked demo scenarios (slide-safe at N≥5)
SHOWCASE_SUITE: tuple[str, ...] = ("books_verify_trap",)

SKIP_SUITE: tuple[str, ...] = (
    "flight_sfo_india",
    "books_tool_fix",
    "books_huge_eval",
    "example_tool_output_cap",
)

ALL_SUITE: tuple[str, ...] = tuple(
    dict.fromkeys([*FAIR_SUITE, *TRAP_SUITE, *CAP_SUITE, *SHOWCASE_SUITE])
)

SUITE_BY_NAME: dict[str, tuple[str, ...]] = {
    "fair_suite": FAIR_SUITE,
    "trap_suite": TRAP_SUITE,
    "cap_suite": CAP_SUITE,
    "showcase_suite": SHOWCASE_SUITE,
    "all": ALL_SUITE,
}

# Backward-compatible aliases
POLICY_SUITE = FAIR_SUITE
STRESS_SUITE = TRAP_SUITE
STEER_SUITE = CAP_SUITE
COST_SHOWCASE_SUITE = SHOWCASE_SUITE


def get_scenario(scenario_id: str) -> LiveScenario:
    key = scenario_id.lower().replace("-", "_")
    if key not in SCENARIOS:
        known = ", ".join(sorted(SCENARIOS))
        raise KeyError(f"unknown scenario {scenario_id!r}; known: {known}")
    return SCENARIOS[key]

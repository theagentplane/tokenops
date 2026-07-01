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


EXAMPLE_TIGHT_CAP = LiveScenario(
    id="example_tight_cap",
    description="Trivial finish under tight cap — cost_guard / cost_budget",
    default_limit_usd=0.30,
    default_max_steps=12,
    task="""
On https://example.com, report the page title and the first sentence of the body text.
Reply with a one-line summary, then call done with success=true.
Do not navigate elsewhere.
""".strip(),
)

BOOKS_LOOP_TRAP = LiveScenario(
    id="books_loop_trap",
    description="Stable site, loop-prone — progress_guard",
    default_limit_usd=0.50,
    default_max_steps=20,
    task="""
Go to https://books.toscrape.com and find the book "A Light in the Attic".
Report its price (including currency) and whether it is in stock.
If you cannot find it after two attempts, try a different navigation path (e.g. search or categories).
Finish with a short summary. Do not book or purchase anything.
""".strip(),
)

FLIGHT_SFO_INDIA = LiveScenario(
    id="flight_sfo_india",
    description="Hard travel UI (not recommended for policy A/B)",
    default_limit_usd=1.00,
    default_max_steps=25,
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
    description="Loop-bait verification under tight cap — progress_guard INJECT vs vanilla overspend",
    default_limit_usd=0.034,
    default_max_steps=20,
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
    description="Deep catalogue crawl under tight cap — cost_guard / cost_budget",
    default_limit_usd=0.10,
    default_max_steps=22,
    task="""
On https://books.toscrape.com, find the book "The Requiem Red" (not on the homepage).
You must browse forward through the catalogue using the "next" page link one page at a time
starting from page 1 — do not jump directly to a page URL.
Report its price and stock. Call done with success=true when found.
""".strip(),
)

EXAMPLE_VERIFY_TRAP = LiveScenario(
    id="example_verify_trap",
    description="Reload loop on cheap page — progress_guard INJECT vs vanilla overspend",
    default_limit_usd=0.018,
    default_max_steps=15,
    task="""
On https://example.com, read the page title and first sentence of body text.

Before finishing, reload the page and re-read the same fields at least eight more times
(nine reload cycles total). Then call done with success=true and a one-line summary.
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
    )
}

# Default suite for policy-focused live A/B
POLICY_SUITE: tuple[str, ...] = ("example_tight_cap", "books_loop_trap")

# Scenarios designed to surface vanilla failure modes TokenOps mitigates
STRESS_SUITE: tuple[str, ...] = (
    "example_verify_trap",
    "books_verify_trap",
    "books_pagination_stress",
)


def get_scenario(scenario_id: str) -> LiveScenario:
    key = scenario_id.lower().replace("-", "_")
    if key not in SCENARIOS:
        known = ", ".join(sorted(SCENARIOS))
        raise KeyError(f"unknown scenario {scenario_id!r}; known: {known}")
    return SCENARIOS[key]

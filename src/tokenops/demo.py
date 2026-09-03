"""The 30-second demo. Ships inside the package so `pip install` is enough.

    python -m tokenops.demo

Runs the same agent loop twice, once ungoverned and once governed, so the
difference is a number rather than a claim. No API keys, no server, no Docker:
the "model" is a local stub, so this costs nothing and touches no network.

The governed half is the real integration. Swap ``fake_llm`` for
``tokenops.providers.complete`` and it is exactly what you would ship.
"""

from __future__ import annotations

import os

from tokenops.providers.types import ModelResponse

# Demo runs in-process. Point TOKENOPS_URL at a control plane instead when
# several agent processes have to share one budget.
os.environ.setdefault("TOKENOPS_EMBEDDED", "1")

BUDGET_MICROS = 2_000_000  # $2.00, from src/tokenops/config/default.yaml
MAX_CALLS = 40


def _fake_llm_factory():
    """A stand-in model. Reports the token usage TokenOps prices."""
    calls = {"n": 0}

    def fake_llm(provider, model, messages, max_output_tokens=None, **kwargs):
        calls["n"] += 1
        return ModelResponse(
            content=f"answer {calls['n']}", input_tokens=50_000, output_tokens=2_000
        )

    return fake_llm, calls


def _price_micros(input_tokens: int, output_tokens: int) -> int:
    """gpt-4o list price, the same book the ledger uses."""
    from tokenops.control.core import Usage
    from tokenops.control.pricing import build_price_book

    price = build_price_book()
    return price("openai", "gpt-4o", Usage(input=input_tokens, output=output_tokens))


def run_ungoverned() -> int:
    """What an agent with a bug does today: keeps calling, nobody stops it."""
    fake_llm, _ = _fake_llm_factory()
    spent = 0
    for _ in range(MAX_CALLS):
        r = fake_llm("openai", "gpt-4o", [{"role": "user", "content": "hi"}])
        spent += _price_micros(r.input_tokens, r.output_tokens)
    return spent


def run_governed() -> tuple[int, int, str]:
    """The same loop with TokenOps in front of the model call."""
    from tokenops import ControlPlaneClient, tokenops_run
    from tokenops.control import Halt, wrap_complete

    fake_llm, _ = _fake_llm_factory()
    client = ControlPlaneClient.from_env()

    with tokenops_run(
        client=client, service="demo", intent="demo", provider="openai", model="gpt-4o"
    ) as bound:
        governed = wrap_complete(
            bound.governor,
            bound.controls,
            bound.attr,
            provider="openai",
            model="gpt-4o",
            dispatch=fake_llm,
            service="demo",
        )
        ledger, run_id = bound.governor.ledger, bound.attr.run_id
        for i in range(1, MAX_CALLS + 1):
            try:
                governed("openai", "gpt-4o", [{"role": "user", "content": f"question {i}"}])
            except Halt as halt:
                return ledger.cost_micros(run_id), i, str(halt)
        return ledger.cost_micros(run_id), MAX_CALLS, "never halted"


def main() -> None:
    dollars = lambda micros: f"${micros / 1e6:,.2f}"  # noqa: E731

    print(
        f"\nAn agent makes {MAX_CALLS} model calls. Budget for the whole run: "
        f"{dollars(BUDGET_MICROS)}.\n"
    )

    ungoverned = run_ungoverned()
    print(f"  without TokenOps   {MAX_CALLS} calls run, spend {dollars(ungoverned)}")

    spent, stopped_at, reason = run_governed()
    print(f"  with TokenOps      halted at call {stopped_at}, spend {dollars(spent)}")

    saved = ungoverned - spent
    print(f"\n  {dollars(saved)} not spent. The run stopped itself.")
    print(f"  reason: {reason}\n")
    print("No single call was expensive. Together they crossed the cap, which is")
    print("what a per-request limit cannot see.\n")
    print(
        "Put this in your own agent:  https://github.com/theagentplane/tokenops#2-put-it-in-your-agent\n"
    )


if __name__ == "__main__":
    main()

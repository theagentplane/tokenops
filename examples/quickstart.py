"""Smallest possible TokenOps run: no API keys, no server, no Docker.

    python examples/quickstart.py

One run makes repeated model calls. TokenOps accounts for every call against a
single run budget and halts the run the moment the budget is exhausted, so the
agent cannot keep spending. The "model" here is a local stub, so this costs
nothing and needs no network.

Swap ``fake_llm`` for ``tokenops.providers.complete`` and this is the real
integration. See the README "Start hacking" section for the next step.
"""

from __future__ import annotations

import os

# Embedded mode keeps the ledger in-process. Point TOKENOPS_URL at a running
# control plane instead when several agent processes must share one budget.
os.environ.setdefault("TOKENOPS_EMBEDDED", "1")

from tokenops import ControlPlaneClient, tokenops_run  # noqa: E402
from tokenops.control import Halt, wrap_complete  # noqa: E402
from tokenops.providers.types import ModelResponse  # noqa: E402

CALLS = 0


def fake_llm(provider, model, messages, max_output_tokens=None, **kwargs):
    """Stand-in for a real model call. Reports the token usage TokenOps bills."""
    global CALLS
    CALLS += 1
    return ModelResponse(content=f"answer {CALLS}", input_tokens=50_000, output_tokens=2_000)


def main() -> None:
    client = ControlPlaneClient.from_env()

    with tokenops_run(
        client=client,
        service="quickstart",
        intent="quickstart",
        provider="openai",
        model="gpt-4o",
    ) as bound:
        # wrap_complete is the enforcement point: detect -> decide -> apply runs
        # BEFORE each call, and the ledger is updated after it.
        governed = wrap_complete(
            bound.governor,
            bound.controls,
            bound.attr,
            provider="openai",
            model="gpt-4o",
            dispatch=fake_llm,
            service="quickstart",
        )

        ledger, run_id = bound.governor.ledger, bound.attr.run_id
        print(f"run {run_id}: budget $2.00 (from src/tokenops/config/default.yaml)\n")

        for i in range(1, 40):
            try:
                governed("openai", "gpt-4o", [{"role": "user", "content": f"question {i}"}])
            except Halt as halt:
                print(f"call {i:>2}: HALTED   spend ${ledger.cost_micros(run_id) / 1e6:.4f}")
                print(f"\n{halt}")
                print("\nThe run is now flagged halted. Later calls on this run_id are refused.")
                return
            print(f"call {i:>2}: ok       spend ${ledger.cost_micros(run_id) / 1e6:.4f}")


if __name__ == "__main__":
    main()

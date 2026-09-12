"""The 30-second demo. Ships inside the package so `pip install` is enough.

    python -m tokenops.demo

Runs the same agent loop twice, once ungoverned and once governed, so the
difference is a number rather than a claim. No API keys the "model" is a local
stub, so this costs nothing and touches no network for the model call itself.

tokenops has no ledger of its own (tokenops#118) — every run governs against a
real control plane. If ``CONTROL_PLANE_URL``/``TOKENOPS_URL`` is already set, the
demo uses it. Otherwise it launches a real, throwaway ``agentplane-control-plane``
in-process (see ``tokenops.control.dev_plane``) so the zero-setup promise holds;
that needs ``agentplane-control-plane`` importable (``pip install
agentplane-control-plane`` once released, or ``pip install
"agent-tokenops[contract]"`` today) — without it, point ``CONTROL_PLANE_URL`` at a
control plane you're already running (``control-plane serve``, or its Docker image).

The governed half is the real integration. Swap ``fake_llm`` for
``tokenops.providers.complete`` and it is exactly what you would ship.
"""

from __future__ import annotations

import os
import sys
import tempfile
from collections.abc import Callable

from tokenops.providers.types import ModelResponse

BUDGET_MICROS = 2_000_000  # $2.00, from src/tokenops/config/default.yaml
MAX_CALLS = 40


def _ensure_control_plane_url() -> tuple[str | None, Callable[[], None] | None]:
    """Return ``(url_to_restore_on_exit, stop_callable_or_None)``.

    If a control plane is already configured, do nothing. Otherwise launch one
    in-process and point ``CONTROL_PLANE_URL`` at it for the life of this process.
    """
    existing = (
        os.environ.get("CONTROL_PLANE_URL")
        or os.environ.get("TOKENOPS_URL")
        or os.environ.get("TOKENOPS_CONTROL_PLANE_URL")
        or ""
    ).strip()
    if existing:
        return None, None
    try:
        from tokenops.control.dev_plane import launch
    except ImportError:
        print(
            "No CONTROL_PLANE_URL is set, and agentplane-control-plane isn't "
            "installed to launch one for you.\n"
            "Either:\n"
            '  pip install "agent-tokenops[contract]"   # launches one automatically\n'
            "or run one yourself (control-plane serve / its Docker image) and set\n"
            "  CONTROL_PLANE_URL=http://localhost:8800\n",
            file=sys.stderr,
        )
        sys.exit(1)
    db = os.path.join(tempfile.mkdtemp(prefix="tokenops-demo-"), "control-plane.db")
    plane = launch(db)
    os.environ["CONTROL_PLANE_URL"] = plane.url
    return plane.url, plane.stop


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


def _seed_governance(url: str) -> None:
    """Configure the same budget + policy the README quotes, via the plane's own
    HTTP API — not a file the plane happens to read, so this is exactly what a
    real deployment would do to configure governance."""
    import httpx

    httpx.put(
        f"{url}/v1/budgets",
        json={
            "id": "run_llm_cap",
            "limit_micros": BUDGET_MICROS,
            "dimension": "run",
            "period": "lifetime",
        },
        timeout=10,
    ).raise_for_status()
    httpx.put(
        f"{url}/v1/policies",
        json={
            "id": "demo_cost_budget",
            "template": "cost_budget",
            "params": {},
            "budget_id": "run_llm_cap",
            "agent": None,
            "segment_id": None,
            "enabled": True,
            "data_scope": "local",
        },
        timeout=10,
    ).raise_for_status()


def main() -> None:
    dollars = lambda micros: f"${micros / 1e6:,.2f}"  # noqa: E731

    url, stop_plane = _ensure_control_plane_url()
    try:
        if url is not None:
            _seed_governance(url)

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
    finally:
        if stop_plane is not None:
            stop_plane()


if __name__ == "__main__":
    main()

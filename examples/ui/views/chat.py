from __future__ import annotations

from typing import Any

import streamlit as st

from examples.a2a.client import check_health_sync, submit_task_sync, submit_task_sync_with_meta
from tokenops.control.models import GovernanceMode
from examples.agents.types import RunResult
from examples.app_config import load_config
from examples.ui.demo_chips import CHIPS, ChipId, live_governance_banner, prepare_chip_governance
from tokenops.ui.store_client import get_store
from tokenops.ui.theme import GOLD, page_shell, status_pill

page_shell(subtitle="Research → Summarize · governed agent pipeline")

st.markdown(
    f"""
    <style>
    .block-container {{ max-width: 52rem; }}
    div[data-testid="stHorizontalBlock"] button[kind="secondary"] {{
        border: 1px solid {GOLD};
        color: {GOLD};
        background: rgba(201, 162, 39, 0.08);
        border-radius: 999px;
        font-weight: 600;
    }}
    div[data-testid="stHorizontalBlock"] button[kind="secondary"]:hover {{
        border-color: {GOLD};
        color: #0A0A0A;
        background: {GOLD};
    }}
    .chip-hint {{
        color: #9A9588;
        font-size: 0.82rem;
        margin: 0.35rem 0 1rem 0;
    }}
    </style>
    """,
    unsafe_allow_html=True,
)


def _init_chat() -> None:
    if "chat_messages" not in st.session_state:
        st.session_state.chat_messages = [
            {
                "role": "assistant",
                "content": (
                    "Pick a **demo chip** to see governance in action, or type your own question below."
                ),
            }
        ]


def _result_payload(
    result: RunResult,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "summary": result.summary,
        "findings": [f.to_dict() for f in result.findings],
        "steps": [s.display_row() for s in result.steps],
        "token_usage": result.token_usage.to_dict(),
    }
    if meta:
        payload.update(meta)
    return payload


def _render_assistant_turn(msg: dict[str, Any]) -> None:
    gov = msg.get("governance")
    if gov:
        st.markdown(gov)
    st.markdown(msg.get("content", ""))
    result = msg.get("result")
    if not result:
        return
    findings = result.get("findings") or []
    steps = result.get("steps") or []
    tokens = result.get("token_usage") or {}
    status = result.get("status")
    if status:
        cost_micros = int(result.get("cost_micros", 0))
        # Simulator uses research_cost_micros + summarize_cost_micros; live uses cost_micros.
        if not cost_micros:
            cost_micros = int(result.get("research_cost_micros", 0)) + int(result.get("summarize_cost_micros", 0))
        show_cost = bool(result.get("show_cost", False)) or "cost_micros" in result
        if show_cost:
            total = cost_micros / 1_000_000
            st.caption(f"Status: {status} · run spend ${total:.4f}")
        else:
            st.caption(f"Status: {status}")
        run_id = result.get("run_id")
        if run_id:
            st.markdown(
                f'<span id="tokenops-run-id" data-run-id="{run_id}"></span>',
                unsafe_allow_html=True,
            )
            st.caption(f"Run ID: {run_id} · [View in Dashboard](/dashboard?run_id={run_id})")
    if findings:
        with st.expander(f"Findings ({len(findings)})", expanded=False):
            for i, f in enumerate(findings, 1):
                st.markdown(f"**{i}. {f.get('query', '')}**")
                st.caption(f"Completeness: {f.get('completeness', 0):.0%}")
                st.write(f.get("snippet", ""))
    if steps:
        with st.expander(f"Agent trace ({len(steps)} steps)", expanded=False):
            st.dataframe(steps, use_container_width=True, hide_index=True)
    if tokens:
        inp = tokens.get("input_tokens", 0)
        out = tokens.get("output_tokens", 0)
        st.caption(f"Tokens — in: {inp:,} · out: {out:,}")


def _append_user(text: str) -> None:
    st.session_state.chat_messages.append({"role": "user", "content": text})


def _append_assistant(
    content: str,
    *,
    result: dict[str, Any] | None = None,
    governance: str | None = None,
) -> None:
    st.session_state.chat_messages.append(
        {
            "role": "assistant",
            "content": content,
            "result": result,
            "governance": governance,
        }
    )


def _run_live_prompt(prompt: str, *, governance_mode: GovernanceMode) -> None:
    cfg = load_config()
    if not check_health_sync(cfg.research.url):
        _append_assistant("Research server is offline. Run `make run` from the repo root.")
        return

    show_cost = governance_mode is GovernanceMode.PREVIEW
    governance_line = (
        "**Governance OFF** — budget ignored (spend may exceed the cap)"
        if show_cost
        else "**Governance ON** — budget/cost policies enforced"
    )
    try:
        result, meta = submit_task_sync_with_meta(
            cfg.research.url,
            prompt,
            corpus_profile="healthy",
            intent="chat_custom",
            governance_mode=governance_mode,
        )
        payload = _result_payload(result, {**meta, "show_cost": show_cost})
        _append_assistant(result.summary or "_No summary returned._", result=payload, governance=governance_line)
    except Exception as exc:
        _append_assistant(f"Run failed: {exc}")


def _run_chip_live(chip_id: ChipId, *, governance_mode: GovernanceMode) -> None:
    cfg = load_config()
    store = get_store()
    chip = prepare_chip_governance(store, chip_id)

    _append_user(chip.prompt)

    show_cost = governance_mode is GovernanceMode.PREVIEW

    try:
        result, meta = submit_task_sync_with_meta(
            cfg.research.url,
            chip.prompt,
            corpus_profile="healthy",
            intent=f"chat_{chip_id}",
            governance_mode=governance_mode,
        )
        payload = _result_payload(result, {**meta, "show_cost": show_cost})
        governance_line = live_governance_banner(chip_id, meta, governance_mode=governance_mode)
        body = result.summary or "_No summary returned._"
        _append_assistant(body, result=payload, governance=governance_line)
    except Exception as exc:
        _append_assistant(f"Run failed: {exc}")


def render_sidebar() -> GovernanceMode:
    cfg = load_config()
    research_ok = check_health_sync(cfg.research.url)
    summarize_ok = check_health_sync(cfg.summarize.url)
    st.sidebar.markdown(
        status_pill("Research", research_ok) + " " + status_pill("Summarize", summarize_ok),
        unsafe_allow_html=True,
    )
    st.sidebar.markdown("---")
    gov_val = st.sidebar.slider(
        "Governance mode (0=OFF, 1=ON)",
        min_value=0,
        max_value=1,
        value=1,
        step=1,
        help="OFF uses preview governance (detect+decide, no enforcement) so spend can exceed the cap.",
    )
    governance_mode = GovernanceMode.ENFORCE if gov_val == 1 else GovernanceMode.PREVIEW
    st.sidebar.caption(f"Effective: {'ON' if governance_mode is GovernanceMode.ENFORCE else 'OFF'}")

    if st.sidebar.button("Clear chat", use_container_width=True):
        st.session_state.chat_messages = []
        _init_chat()
        st.rerun()

    return governance_mode


_init_chat()
governance_mode = render_sidebar()

for msg in st.session_state.chat_messages:
    with st.chat_message(msg["role"]):
        if msg["role"] == "assistant":
            _render_assistant_turn(msg)
        else:
            st.markdown(msg["content"])

chip_cols = st.columns(len(CHIPS))
for col, chip in zip(chip_cols, CHIPS):
    with col:
        if st.button(chip.label, key=f"chip_{chip.id}", use_container_width=True, type="secondary"):
            _run_chip_live(chip.id, governance_mode=governance_mode)
            st.rerun()

st.markdown(
    "<p class=\"chip-hint\">"
    "<b>Left</b>: hard stop (cost cap) · <b>Right</b>: minimize (cost guard)"
    "</p>",
    unsafe_allow_html=True,
)

prompt = st.chat_input("Or ask your own question…")
if prompt:
    _append_user(prompt)
    _run_live_prompt(prompt, governance_mode=governance_mode)
    st.rerun()

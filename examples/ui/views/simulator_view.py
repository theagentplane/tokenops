"""Run simulator — trigger a governed run in-process and inspect trace + control plane."""

from __future__ import annotations

import pandas as pd
import streamlit as st
import yaml

from examples.app_config import load_config
from tokenops.env import load_env
from examples.ui.simulator import (
    SimulationResult,
    event_timeline,
    run_simulation,
    window_rows,
)
from tokenops.ui.store_client import get_store
from tokenops.ui.theme import page_shell

load_env()

page_shell(subtitle="In-process governed run · live trace and control-plane events")

cfg = load_config()
store = get_store()

with st.sidebar:
    st.markdown("### Run inputs")
    task = st.text_area("Task", cfg.task, height=80)
    demo_scenario = st.selectbox(
        "Demo scenario",
        ["default", "search_loop_trap", "shared_ledger_cap"],
        format_func=lambda s: {
            "default": "Default — two searches then finish",
            "search_loop_trap": "Search loop trap — progress_guard",
            "shared_ledger_cap": "Shared ledger cap — run prep_ledger_comparison.py first",
        }[s],
    )
    if demo_scenario == "search_loop_trap":
        corpus_profile = "leak"
        st.caption("Corpus: **leak** (fixed for this scenario). Set `SEARCH_BACKEND=corpus` before starting UI.")
    else:
        corpus_profile = st.selectbox("Corpus profile", ["healthy", "leak"], index=0)
    demo_mode = st.toggle("Demo mode (stub LLM)", value=True, help="No API key needed.")
    preview_mode = st.toggle(
        "Preview mode (no enforcement)",
        value=False,
        help="Policies detect and decide, but actions are not pushed to the agent.",
    )
    if not demo_mode:
        st.warning("Live mode calls real providers — ensure API keys are set.")

    st.markdown("#### Registration")
    intent = st.text_input("Intent", "simulator_demo")
    country = st.text_input("Country", "US")
    user_id = st.text_input("user_id", "simulator")
    custom_tags_raw = st.text_area(
        "Custom tags (key=value per line)", "team=growth", height=70,
        help="Segment runs by any tag — group/filter them on the Dashboard.",
    )

    st.markdown("#### Agents")
    _default_steps = 12 if demo_scenario == "search_loop_trap" else 5
    max_steps = st.number_input("Research max steps", min_value=1, max_value=50, value=_default_steps)
    if demo_scenario == "search_loop_trap":
        st.caption("Use **max steps ≥ 8** so the stub can repeat search enough times.")


def _parse_tags(raw: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in raw.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            if k.strip():
                out[k.strip()] = v.strip()
    return out


start = st.button("Start run", type="primary", use_container_width=True)

if start:
    live_log = st.empty()
    events_buf: list[str] = []

    def on_event(ev) -> None:
        line = f"`{ev.category}` **{ev.title}**" + (f" ({ev.agent})" if ev.agent else "")
        events_buf.append(line)
        with live_log.container():
            st.markdown("#### Live timeline")
            for row in events_buf[-25:]:
                st.markdown(f"- {row}")

    with st.status("Running governed pipeline…", expanded=True) as status:
        try:
            from examples.app_config import AgentServerConfig
            from tokenops.control.models import GovernanceMode

            _sat = (
                0.99
                if demo_scenario == "search_loop_trap"
                else cfg.research.satisfaction_threshold
            )
            result = run_simulation(
                store,
                task=task,
                corpus_profile=corpus_profile,
                intent=intent,
                user_dims={"Country": country, "user_id": user_id, **_parse_tags(custom_tags_raw)},
                demo_scenario=demo_scenario,
                research_cfg=AgentServerConfig(
                    provider=cfg.research.provider,
                    model=cfg.research.model,
                    max_steps=int(max_steps),
                    satisfaction_threshold=_sat,
                ),
                summarize_cfg=AgentServerConfig(
                    provider=cfg.summarize.provider,
                    model=cfg.summarize.model,
                ),
                demo_mode=demo_mode,
                governance_mode=(
                    GovernanceMode.PREVIEW if preview_mode else GovernanceMode.ENFORCE
                ),
                on_event=on_event,
            )
            st.session_state.sim_result = result
            label = f"Run {result.status} — {result.run_id}"
            state = "complete" if result.status == "completed" else "error"
            status.update(label=label, state=state)
        except Exception as exc:
            status.update(label="Run failed", state="error")
            st.error(str(exc))
            st.stop()

if "sim_result" not in st.session_state:
    st.info("Configure inputs in the sidebar and click **Start run**.")
    st.stop()

result: SimulationResult = st.session_state.sim_result

# ---- summary bar --------------------------------------------------------- #
cap_spec = store.get_budget("run_llm_cap")
budget_cap_micros = cap_spec.limit_micros if cap_spec and cap_spec.limit_micros else None
total_micros = result.research_cost_micros + result.summarize_cost_micros

c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Run ID", result.run_id[:16] + "…")
c2.metric("Status", result.status)
c3.metric("Research $", f"${result.research_cost_micros / 1_000_000:.4f}")
c4.metric("Summarize $", f"${result.summarize_cost_micros / 1_000_000:.4f}")
c5.metric("Total run $", f"${total_micros / 1_000_000:.4f}")
if budget_cap_micros is not None:
    over = total_micros > budget_cap_micros
    c6.metric(
        "Run budget cap",
        f"${budget_cap_micros / 1_000_000:.4f}",
        delta="over cap" if over else "within cap",
        delta_color="inverse" if over else "normal",
    )
else:
    c6.metric("Steps (ledger)", len(result.research_window) + len(result.summarize_window))

if result.halt_reason:
    st.warning(f"Halt reason: {result.halt_reason}")

tab_out, tab_trace, tab_ctrl, tab_timeline = st.tabs(
    ["Output", "Trace & spans", "Control plane", "Timeline"]
)

with tab_out:
    st.subheader("Summary")
    st.write(result.summary or "_(no summary — run may have halted early)_")

    st.subheader("Findings")
    if result.findings:
        st.dataframe([f.to_dict() for f in result.findings], use_container_width=True)
    else:
        st.caption("No findings.")

    st.subheader("Agent step log")
    if result.steps:
        st.dataframe([s.display_row() for s in result.steps], use_container_width=True)

    with st.expander("Registration"):
        st.json(
            {
                "run_id": result.registration.run_id,
                "intent": result.registration.intent,
                "user_dims": result.registration.user_dims,
            }
        )

with tab_trace:
    st.subheader("Span context")
    span_events = [e for e in result.events if e.category in ("span", "observe", "chronicle")]
    if span_events:
        rows = []
        for e in span_events:
            d = e.detail
            rows.append(
                {
                    "category": e.category,
                    "agent": e.agent,
                    "title": e.title,
                    "span_id": (d.get("span_id") or "")[:12],
                    "parent_span_id": (d.get("parent_span_id") or "")[:12] or "—",
                    "service": d.get("service", e.agent),
                    "boundary_id": d.get("boundary_id", ""),
                    "node_type": d.get("node_type", d.get("kind", "")),
                }
            )
        st.dataframe(pd.DataFrame(rows), use_container_width=True)
    else:
        st.caption("No span events recorded.")

    st.subheader("Chronicle envelopes")
    if result.envelopes:
        env_rows = []
        for env in result.envelopes:
            env_rows.append(
                {
                    "sequence": env.sequence,
                    "boundary_id": env.node_id,
                    "kind": env.boundary_kind,
                    "parent_envelope": (env.parent_envelope_id or "—")[:12],
                    "invocation": env.invocation_index,
                }
            )
        st.dataframe(pd.DataFrame(env_rows), use_container_width=True)
        with st.expander("Envelope detail"):
            for env in result.envelopes:
                st.markdown(f"**{env.node_id}** (#{env.sequence})")
                st.json(
                    {
                        "envelope_id": env.envelope_id,
                        "trace_id": env.trace_id,
                        "parent_envelope_id": env.parent_envelope_id,
                        "input": env.input_state.graph_state if env.input_state else {},
                        "completion": (env.action_result.completion or "")[:200],
                    }
                )
    else:
        st.caption("No Chronicle envelopes (tool @boundary crossings record here).")

    st.subheader("Trace ID")
    st.code(result.trace_id)

with tab_ctrl:
    st.subheader("Policy signals & actions")
    ctrl_events = [e for e in result.events if e.category in ("pre_call", "signal", "action", "halt", "throttle")]
    if ctrl_events:
        st.dataframe(pd.DataFrame([e.to_row() for e in ctrl_events]), use_container_width=True)
    else:
        st.caption("No control-plane enforcement events (policies may have stayed OK).")

    col_r, col_s = st.columns(2)
    with col_r:
        st.subheader("Research ledger window")
        if result.research_window:
            st.dataframe(pd.DataFrame(window_rows(result.research_window)), use_container_width=True)
        else:
            st.caption("Empty.")
    with col_s:
        st.subheader("Summarize ledger window")
        if result.summarize_window:
            st.dataframe(pd.DataFrame(window_rows(result.summarize_window)), use_container_width=True)
        else:
            st.caption("Empty.")

    st.subheader("Attribution tags (from registration)")
    from tokenops.control import build_attribution

    attr = build_attribution(result.registration, service="research")
    st.json({"user": attr.user, "agent": attr.agent, "run_id": attr.run_id, "tags": attr.tags})

with tab_timeline:
    st.subheader("Full event log")
    st.dataframe(pd.DataFrame(event_timeline(result.events)), use_container_width=True, height=400)
    with st.expander("Raw events JSON"):
        st.code(
            yaml.safe_dump(
                [
                    {
                        "ts": e.ts,
                        "category": e.category,
                        "title": e.title,
                        "agent": e.agent,
                        "detail": e.detail,
                    }
                    for e in result.events
                ],
                sort_keys=False,
            ),
            language="yaml",
        )

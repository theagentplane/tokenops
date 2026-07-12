"""Dashboard — agent runs, run detail with governance trace, and cost reporting."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from tokenops.ui.run_detail import render_run_detail
from tokenops.ui.store_client import get_store
from tokenops.ui.theme import page_shell

page_shell(subtitle="Run history, costs, and governance trace (read-only)")
store = get_store()

runs = store.list_runs(limit=500)
if not runs:
    st.info("No runs yet. Start one from **Chat** or **Simulator**.")
    st.stop()


def _usd(micros: int) -> float:
    return round(micros / 1_000_000, 6)


def _duration(r) -> float | None:
    return round(r.ended_at - r.started_at, 2) if r.ended_at else None


run_ids = [r.run_id for r in runs]
qp_run = st.query_params.get("run_id")
focus_run = qp_run if qp_run in run_ids else None

# ---- focused run (from Chat link / demo video) ---------------------------- #
if focus_run:
    detail = store.get_run(focus_run)
    if detail:
        st.subheader("Run detail")
        render_run_detail(store, detail)
        st.markdown("---")

# ---- active governance (read-only) --------------------------------------- #
with st.expander("Active governance (read-only)", expanded=False):
    gov_agent = st.selectbox("Agent", ["research", "summarize"], key="dash_gov_agent")
    cfg = store.governance_config_for(gov_agent)
    budgets = cfg["governance"].get("budgets", [])
    policies = cfg["governance"].get("policies", {})
    if not policies:
        st.warning("No policies configured — run `make db-reseed` or add them in Policy admin.")
    else:
        st.markdown(f"**{len(budgets)}** budget(s), **{len(policies)}** policy template(s) for `{gov_agent}`")
        if budgets:
            st.markdown("**Budgets**")
            st.dataframe(
                [
                    {
                        "id": b["id"],
                        "limit_usd": None if b.get("limit_micros") is None else b["limit_micros"] / 1_000_000,
                        "dimension": b.get("dimension", "run"),
                    }
                    for b in budgets
                ],
                use_container_width=True,
                hide_index=True,
            )
        st.markdown("**Policies → budget link**")
        st.dataframe(
            [
                {
                    "template": name,
                    "budget": params.get("budget", "—"),
                    "params": {k: v for k, v in params.items() if k != "budget"},
                }
                for name, params in sorted(policies.items())
            ],
            use_container_width=True,
            hide_index=True,
        )

fleet_expanded = not focus_run
with st.expander("Fleet overview", expanded=fleet_expanded):
    total_cost = sum(r.cost_micros for r in runs)
    problematic = [r for r in runs if r.problematic]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Runs", len(runs))
    c2.metric("Total cost", f"${_usd(total_cost):.4f}")
    c3.metric("Problematic", len(problematic))
    c4.metric("Avg $/run", f"${_usd(total_cost // max(1, len(runs))):.4f}")

    tag_keys = store.run_tag_keys()
    group_by = st.selectbox("Segment by", ["agent"] + tag_keys, key="dash_group_by",
                            help="Group runs by agent, or by any custom tag emitted on the run "
                                 "(set tags in the Run simulator or via user_dims on /v1/runs).")

    def _seg(r) -> str:
        return r.agent if group_by == "agent" else (r.dims.get(group_by) or "—")

    seg_cost: dict[str, int] = {}
    seg_runs: dict[str, int] = {}
    for r in runs:
        sv = _seg(r)
        seg_cost[sv] = seg_cost.get(sv, 0) + r.cost_micros
        seg_runs[sv] = seg_runs.get(sv, 0) + 1

    st.subheader(f"Cost by {group_by}")
    st.bar_chart(pd.DataFrame({"cost_usd": {s: _usd(m) for s, m in seg_cost.items()}}))
    st.dataframe(
        pd.DataFrame([{group_by: s, "runs": seg_runs[s], "cost_usd": _usd(seg_cost[s])}
                      for s in sorted(seg_cost)]),
        use_container_width=True, hide_index=True,
    )

    st.subheader("Runs")
    fcol1, fcol2 = st.columns(2)
    only_bad = fcol1.toggle("Problematic only (halted / throttled / error)", key="dash_only_bad")
    seg_values = ["(all)"] + sorted({_seg(r) for r in runs})
    pick = fcol2.selectbox(f"Filter by {group_by}", seg_values, key="dash_seg_filter")
    shown = [r for r in (problematic if only_bad else runs) if pick == "(all)" or _seg(r) == pick]
    table = pd.DataFrame([{
        "run_id": r.run_id, "agent": r.agent, "status": r.status,
        "cost_usd": _usd(r.cost_micros), "steps": r.steps,
        "duration_s": _duration(r), "dims": r.dims, "halt_reason": r.halt_reason or "",
        "parent_run": r.parent_run or "",
        "gov_events": len(r.governance_events or []),
    } for r in shown])
    st.dataframe(table, use_container_width=True, hide_index=True)

# ---- run detail picker (when not already focused) ------------------------ #
if not focus_run:
    st.subheader("Run detail")
    default_idx = 0
    pick_run = st.selectbox(
        "Inspect run",
        run_ids,
        index=default_idx,
        format_func=lambda rid: f"{rid} · {store.get_run(rid).status if store.get_run(rid) else '?'}",
        key="dash_pick_run",
    )
    detail = store.get_run(pick_run)
    if detail:
        render_run_detail(store, detail)

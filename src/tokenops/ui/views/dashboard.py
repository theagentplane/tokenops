"""Dashboard — agent runs, run detail with governance trace, and cost reporting."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import asdict
from datetime import datetime, time

import altair as alt
import pandas as pd
import streamlit as st

from tokenops.ui.run_detail import render_run_detail
from tokenops.ui.store_client import get_store
from tokenops.ui.theme import GOLD, MUTED, page_shell

page_shell(subtitle="Run history, costs, and governance trace (read-only)")
store = get_store()

runs = store.list_runs(limit=500)
if not runs:
    st.info("No runs yet. Register a run via the plane (`POST /v1/runs`) or a wiki demo.")
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
    gov_agent = st.text_input(
        "Agent (blank = global policies only)",
        value="",
        key="dash_gov_agent",
        placeholder="e.g. research",
    ).strip()
    cfg = store.governance_config_for(gov_agent or "")
    budgets = cfg["governance"].get("budgets", [])
    policies = cfg["governance"].get("policies", {})
    if not policies:
        st.warning("No policies configured — run `make db-reseed` or add them in Policy admin.")
    else:
        label = gov_agent or "(global)"
        st.markdown(
            f"**{len(budgets)}** budget(s), **{len(policies)}** policy template(s) for `{label}`"
        )
        if budgets:
            st.markdown("**Budgets**")
            st.dataframe(
                [
                    {
                        "id": b["id"],
                        "limit_usd": None
                        if b.get("limit_micros") is None
                        else b["limit_micros"] / 1_000_000,
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
    group_by = st.selectbox(
        "Segment by",
        ["agent"] + tag_keys,
        key="dash_group_by",
        help="Group runs by agent, or by any custom tag emitted on the run "
        "(set tags in the Run simulator or via user_dims on /v1/runs).",
    )

    def _seg(r) -> str:
        return r.agent if group_by == "agent" else (r.dims.get(group_by) or "—")

    seg_cost: dict[str, int] = {}
    seg_runs: dict[str, int] = {}
    for r in runs:
        sv = _seg(r)
        seg_cost[sv] = seg_cost.get(sv, 0) + r.cost_micros
        seg_runs[sv] = seg_runs.get(sv, 0) + 1

    st.subheader(f"Cost by {group_by}")
    chart_df = pd.DataFrame([{group_by: s, "cost_usd": _usd(m)} for s, m in seg_cost.items()])
    chart = (
        alt.Chart(chart_df)
        .mark_bar(color=GOLD, cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
        .encode(
            x=alt.X(f"{group_by}:N", title=None, sort="-y"),
            y=alt.Y("cost_usd:Q", title="Cost (USD)"),
            tooltip=[group_by, "cost_usd"],
        )
        .configure_axis(
            labelColor=MUTED, titleColor=MUTED, domainColor="#E7E4DB", gridColor="#F0EEE7"
        )
        .configure_view(strokeWidth=0)
        .properties(height=260)
    )
    st.altair_chart(chart, use_container_width=True)
    st.dataframe(
        pd.DataFrame(
            [
                {group_by: s, "runs": seg_runs[s], "cost_usd": _usd(seg_cost[s])}
                for s in sorted(seg_cost)
            ]
        ),
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("Runs")
    fcol1, fcol2 = st.columns(2)
    only_bad = fcol1.toggle("Problematic only (halted / throttled / error)", key="dash_only_bad")
    seg_values = ["(all)"] + sorted({_seg(r) for r in runs})
    pick = fcol2.selectbox(f"Filter by {group_by}", seg_values, key="dash_seg_filter")
    shown = [r for r in (problematic if only_bad else runs) if pick == "(all)" or _seg(r) == pick]
    table = pd.DataFrame(
        [
            {
                "run_id": r.run_id,
                "agent": r.agent,
                "status": r.status,
                "cost_usd": _usd(r.cost_micros),
                "steps": r.steps,
                "duration_s": _duration(r),
                "dims": r.dims,
                "halt_reason": r.halt_reason or "",
                "parent_run": r.parent_run or "",
                "gov_events": len(r.governance_events or []),
            }
            for r in shown
        ]
    )
    st.dataframe(table, use_container_width=True, hide_index=True)

# ---- export (CSV / JSON download) ---------------------------------------- #
_EXPORT_COLUMNS = [
    "run_id",
    "agent",
    "status",
    "cost_micros",
    "steps",
    "started_at",
    "ended_at",
    "duration_s",
    "dims",
    "halt_reason",
    "detector",
    "governance_events",
]


def _to_csv(runs_list):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(_EXPORT_COLUMNS)
    for rec in runs_list:
        d = asdict(rec)
        d["duration_s"] = round(rec.ended_at - rec.started_at, 2) if rec.ended_at else ""
        d["dims"] = json.dumps(rec.dims) if rec.dims else ""
        d["governance_events"] = json.dumps(rec.governance_events) if rec.governance_events else ""
        writer.writerow([d.get(c, "") for c in _EXPORT_COLUMNS])
    return buf.getvalue()


def _date_to_epoch(d, end_of_day: bool = False) -> float:
    """Convert a date to epoch seconds. ``end_of_day`` returns 23:59:59.999."""
    t = time.max if end_of_day else time.min
    return datetime.combine(d, t).timestamp()


with st.expander("Export run data", expanded=False):
    agents = sorted({r.agent for r in runs})
    ecol1, ecol2, ecol3, ecol4 = st.columns(4)
    with ecol1:
        export_from = st.date_input("From", value=None, key="export_from")
    with ecol2:
        export_to = st.date_input("To", value=None, key="export_to")
    with ecol3:
        export_agent = st.selectbox("Agent", ["All"] + agents, key="export_agent")
    with ecol4:
        export_status = st.selectbox(
            "Status",
            ["All", "completed", "halted", "error", "running"],
            key="export_status",
        )

    export_runs = store.export_runs(
        from_at=_date_to_epoch(export_from) if export_from else None,
        to_at=_date_to_epoch(export_to, end_of_day=True) if export_to else None,
        agent=export_agent if export_agent != "All" else None,
        status=export_status if export_status != "All" else None,
        limit=10_000,
    )

    st.caption(f"{len(export_runs)} runs matched")
    st.markdown(
        "<style>div[data-testid='stHorizontalBlock']{gap:0.5rem}</style>",
        unsafe_allow_html=True,
    )
    dl_col1, dl_col2, _ = st.columns([1, 1, 6])
    with dl_col1:
        st.download_button(
            "Download CSV",
            data=_to_csv(export_runs),
            file_name="export.csv",
            mime="text/csv",
        )
    with dl_col2:
        st.download_button(
            "Download JSON",
            data=json.dumps([asdict(r) for r in export_runs], default=str, indent=2),
            file_name="export.json",
            mime="application/json",
        )

# ---- run detail picker (when not already focused) ------------------------ #
if not focus_run:
    st.subheader("Run detail")
    default_idx = 0
    pick_run = st.selectbox(
        "Inspect run",
        run_ids,
        index=default_idx,
        format_func=lambda rid: (
            f"{rid} · {store.get_run(rid).status if store.get_run(rid) else '?'}"
        ),
        key="dash_pick_run",
    )
    detail = store.get_run(pick_run)
    if detail:
        render_run_detail(store, detail)

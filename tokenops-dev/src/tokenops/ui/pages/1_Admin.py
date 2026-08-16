"""Admin — create segments, budgets, and policy instances, and link them (goal 3).

Writes to the shared SQLite store; the A2A servers pick up changes on the next run via
``store.governance_config_for(agent)``.
"""

from __future__ import annotations

import json

import streamlit as st

from tokenops.control.config import _TEMPLATES
from tokenops.control.models import BudgetSpec, PolicyInstance, Segment
from tokenops.control.store import new_id
from tokenops.ui.store_client import get_store

st.set_page_config(page_title="TokenOps — Admin", layout="wide")
st.title("Policy admin")
store = get_store()

DIMENSIONS = ["run", "user", "agent", "tenant", "tag"]
AGENTS = ["(all)", "research", "summarize"]

seg_tab, budget_tab, policy_tab = st.tabs(["Segments", "Budgets", "Policies"])

# ---- Segments ------------------------------------------------------------- #
with seg_tab:
    st.caption("A segment is a named, reusable matcher you can attach to budgets and policies.")
    with st.form("seg"):
        name = st.text_input("Name", placeholder="acme tenant")
        dim = st.selectbox("Dimension", DIMENSIONS)
        tag_key = st.text_input("Tag key (only for dimension=tag)")
        if st.form_submit_button("Save segment") and name:
            store.upsert_segment(Segment(id=new_id("seg"), name=name, dimension=dim,
                                         tag_key=tag_key or None))
            st.success(f"saved segment {name!r}")
    st.dataframe([s.__dict__ for s in store.list_segments()], use_container_width=True)

# ---- Budgets -------------------------------------------------------------- #
with budget_tab:
    st.caption("A budget is a spend cap bound to a dimension. Leave limit empty for an "
               "unlimited accumulator (measure only).")
    with st.form("budget"):
        bid = st.text_input("Budget id", placeholder="run_llm_cap")
        unlimited = st.checkbox("Unlimited (accumulator only)")
        limit_usd = st.number_input("Limit (USD)", min_value=0.0, value=2.0, step=0.5,
                                    disabled=unlimited)
        bdim = st.selectbox("Dimension", DIMENSIONS, key="bdim")
        btag = st.text_input("Tag key (dimension=tag)", key="btag")
        if st.form_submit_button("Save budget") and bid:
            limit_micros = None if unlimited else int(limit_usd * 1_000_000)
            store.upsert_budget(BudgetSpec(id=bid, limit_micros=limit_micros, dimension=bdim,
                                           tag_key=btag or None))
            st.success(f"saved budget {bid!r}")
    st.dataframe([b.__dict__ for b in store.list_budgets()], use_container_width=True)

# ---- Policies ------------------------------------------------------------- #
with policy_tab:
    st.caption("A policy instance = a template + params, scoped to an agent, optionally "
               "attached to a budget/segment.")
    budgets = ["(none)"] + [b.id for b in store.list_budgets()]
    segments = ["(none)"] + [s.id for s in store.list_segments()]
    with st.form("policy"):
        template = st.selectbox("Template", sorted(_TEMPLATES))
        params_raw = st.text_area("Params (JSON)", value="{}",
                                  help="e.g. {\"max_steps\": 20} for step_cap")
        agent = st.selectbox("Agent", AGENTS)
        budget_id = st.selectbox("Budget", budgets)
        segment_id = st.selectbox("Segment", segments)
        enabled = st.checkbox("Enabled", value=True)
        if st.form_submit_button("Save policy"):
            try:
                params = json.loads(params_raw or "{}")
                store.upsert_policy_instance(PolicyInstance(
                    id=new_id("pi"), template=template, params=params,
                    agent=None if agent == "(all)" else agent,
                    budget_id=None if budget_id == "(none)" else budget_id,
                    segment_id=None if segment_id == "(none)" else segment_id,
                    enabled=enabled,
                ))
                st.success(f"saved {template} instance")
            except (ValueError, json.JSONDecodeError) as exc:
                st.error(str(exc))  # fail closed: unknown template / bad params rejected

    rows = [{"id": p.id, "template": p.template, "agent": p.agent or "(all)",
             "budget": p.budget_id, "segment": p.segment_id, "enabled": p.enabled,
             "params": json.dumps(p.params)} for p in store.list_policy_instances()]
    st.dataframe(rows, use_container_width=True)

# ---- Effective config preview -------------------------------------------- #
st.subheader("Effective governance config")
preview_agent = st.selectbox("Preview for agent", ["research", "summarize"])
st.json(store.governance_config_for(preview_agent))

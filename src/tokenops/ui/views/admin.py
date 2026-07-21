"""Admin — create, edit, and delete segments, budgets, and policy instances (goal 3).

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
from tokenops.ui.theme import page_shell

page_shell(subtitle="Segments, budgets, and policies — applies on the next agent run")

store = get_store()

DIMENSIONS = ["run", "user", "agent", "tenant", "tag"]
AGENTS = ["(all)", "research", "summarize", "planner", "researcher", "writer"]

# Template-specific param hints for the policy form
_TEMPLATE_DEFAULTS: dict[str, str] = {
    "step_cap": '{"max_steps": 20}',
    "cost_budget": "{}",
    "pre_call_worst_case": '{"default_max_output": 1024}',
    "concurrency_cap": '{"max_concurrent": 4, "mode": "reject"}',
    "tool_fix": '{"registry": ["search"], "k": 3}',
    "tool_output_cap": '{"cap_tokens": 8000}',
    "progress_guard": '{"window": 6, "repeats": 3, "max_corrections": 2}',
    "cost_guard": '{"threshold": 0.8, "mode": "minimize"}',
    "context_compaction": '{"ctx_max": 100000, "has_hook": false}',
    "output_runaway": '{"repeats": 4, "max_retries": 2}',
}

seg_tab, budget_tab, policy_tab = st.tabs(["Segments", "Budgets", "Policies"])

# ---- Segments ------------------------------------------------------------- #
with seg_tab:
    st.caption("A segment is a named, reusable matcher you can attach to budgets and policies.")
    segments = store.list_segments()
    edit_seg = st.selectbox("Edit existing", ["(new)"] + [s.id for s in segments], key="edit_seg")
    seg_prefill = store.get_segment(edit_seg) if edit_seg != "(new)" else None
    _seg_key = edit_seg

    with st.form("seg"):
        sid = st.text_input("Id", value=seg_prefill.id if seg_prefill else new_id("seg"), key=f"seg_id_{_seg_key}")
        name = st.text_input("Name", value=seg_prefill.name if seg_prefill else "", placeholder="acme tenant")
        dim = st.selectbox(
            "Dimension",
            DIMENSIONS,
            index=DIMENSIONS.index(seg_prefill.dimension) if seg_prefill else 0,
        )
        tag_key = st.text_input("Tag key (only for dimension=tag)", value=seg_prefill.tag_key or "" if seg_prefill else "")
        col1, col2 = st.columns(2)
        save = col1.form_submit_button("Save segment", type="primary")
        delete = col2.form_submit_button("Delete", disabled=edit_seg == "(new)")
        if save and name:
            store.upsert_segment(
                Segment(id=sid, name=name, dimension=dim, tag_key=tag_key or None)
            )
            st.success(f"Saved segment {name!r}")
            st.rerun()
        if delete and edit_seg != "(new)":
            store.delete_segment(edit_seg)
            st.success(f"Deleted segment {edit_seg}")
            st.rerun()

    st.dataframe([s.__dict__ for s in store.list_segments()], use_container_width=True)

# ---- Budgets -------------------------------------------------------------- #
with budget_tab:
    st.caption(
        "To **update** a seeded budget (e.g. `run_llm_cap`), select it below and change the limit. "
        "Use the same **Budget id** — a new id creates a separate budget."
    )
    budgets = store.list_budgets()
    edit_bud = st.selectbox("Edit existing", ["(new)"] + [b.id for b in budgets], key="edit_bud")

    if st.session_state.get("_budget_sel") != edit_bud:
        st.session_state._budget_sel = edit_bud
        bud = store.get_budget(edit_bud) if edit_bud != "(new)" else None
        st.session_state.budget_bid = bud.id if bud else ""
        st.session_state.budget_unlimited = bud.limit_micros is None if bud else False
        st.session_state.budget_limit = (
            (bud.limit_micros or 0) / 1_000_000 if bud and bud.limit_micros else 2.0
        )
        st.session_state.budget_dim = bud.dimension if bud else "run"
        st.session_state.budget_tag = bud.tag_key or "" if bud else ""

    with st.form("budget"):
        bid = st.text_input("Budget id", key="budget_bid", placeholder="run_llm_cap")
        unlimited = st.checkbox("Unlimited (accumulator only)", key="budget_unlimited")
        limit_usd = st.number_input(
            "Limit (USD)",
            min_value=0.0,
            step=0.0001,
            format="%.6f",
            key="budget_limit",
            disabled=st.session_state.get("budget_unlimited", False),
        )
        bdim = st.selectbox("Dimension", DIMENSIONS, key="budget_dim")
        btag = st.text_input("Tag key (dimension=tag)", key="budget_tag")
        col1, col2 = st.columns(2)
        save = col1.form_submit_button("Save budget", type="primary")
        delete = col2.form_submit_button("Delete", disabled=edit_bud == "(new)")
        if save:
            bid_val = (bid or "").strip()
            if not bid_val:
                st.error("Budget id is required.")
            else:
                limit_micros = None if unlimited else int(float(limit_usd) * 1_000_000)
                store.upsert_budget(
                    BudgetSpec(
                        id=bid_val,
                        limit_micros=limit_micros,
                        dimension=bdim,
                        tag_key=btag or None,
                    )
                )
                if limit_micros is None:
                    st.success(f"Saved budget {bid_val!r} (unlimited)")
                else:
                    st.success(f"Saved budget {bid_val!r} (${limit_usd:.6f} cap)")
                st.rerun()
        if delete and edit_bud != "(new)":
            store.delete_budget(edit_bud)
            st.warning(f"Deleted budget {edit_bud}.")
            st.rerun()

    st.dataframe(
        [
            {
                "id": b.id,
                "limit_usd": None if b.limit_micros is None else b.limit_micros / 1_000_000,
                "limit_micros": b.limit_micros,
                "dimension": b.dimension,
                "tag_key": b.tag_key,
            }
            for b in store.list_budgets()
        ],
        use_container_width=True,
    )

# ---- Policies ------------------------------------------------------------- #
with policy_tab:
    st.caption(
        "One row per **template** is effective (duplicates: last row wins). "
        "Budget-linked policies need a **Budget** selected — that wires `cost_budget`, "
        "`pre_call_worst_case`, and `cost_guard` to the same spend cap."
    )
    policies = store.list_policy_instances()
    budget_options = ["(none)"] + [b.id for b in store.list_budgets()]
    segment_options = ["(none)"] + [s.id for s in store.list_segments()]
    edit_pol = st.selectbox("Edit existing", ["(new)"] + [p.id for p in policies], key="edit_pol")
    pol_prefill = store.get_policy_instance(edit_pol) if edit_pol != "(new)" else None
    _pol_key = edit_pol

    default_template = pol_prefill.template if pol_prefill else sorted(_TEMPLATES)[0]
    with st.form("policy"):
        pid = st.text_input(
            "Instance id",
            value=pol_prefill.id if pol_prefill else new_id("pi"),
            key=f"policy_id_{_pol_key}",
        )
        template = st.selectbox(
            "Template",
            sorted(_TEMPLATES),
            index=sorted(_TEMPLATES).index(default_template),
        )
        default_params = (
            json.dumps(pol_prefill.params)
            if pol_prefill
            else _TEMPLATE_DEFAULTS.get(template, "{}")
        )
        params_raw = st.text_area(
            "Params (JSON)",
            value=default_params,
            help="Budget-linked templates: leave `{}` here — pick the Budget below.",
        )
        agent_val = pol_prefill.agent if pol_prefill else None
        agent = st.selectbox(
            "Agent",
            AGENTS,
            index=0 if not agent_val else AGENTS.index(agent_val),
            key=f"policy_agent_{_pol_key}",
        )
        bud_default = pol_prefill.budget_id if pol_prefill and pol_prefill.budget_id in budget_options else "(none)"
        budget_id = st.selectbox("Budget", budget_options, index=budget_options.index(bud_default))
        seg_default = pol_prefill.segment_id if pol_prefill and pol_prefill.segment_id in segment_options else "(none)"
        segment_id = st.selectbox("Segment", segment_options, index=segment_options.index(seg_default))
        enabled = st.checkbox("Enabled", value=pol_prefill.enabled if pol_prefill else True)
        col1, col2 = st.columns(2)
        save = col1.form_submit_button("Save policy", type="primary")
        delete = col2.form_submit_button("Delete", disabled=edit_pol == "(new)")
        if save:
            try:
                params = json.loads(params_raw or "{}")
                store.upsert_policy_instance(
                    PolicyInstance(
                        id=pid,
                        template=template,
                        params=params,
                        agent=None if agent == "(all)" else agent,
                        budget_id=None if budget_id == "(none)" else budget_id,
                        segment_id=None if segment_id == "(none)" else segment_id,
                        enabled=enabled,
                    )
                )
                st.success(f"Saved {template} instance {pid!r}")
                st.rerun()
            except (ValueError, json.JSONDecodeError) as exc:
                st.error(str(exc))
        if delete and edit_pol != "(new)":
            store.delete_policy_instance(edit_pol)
            st.success(f"Deleted policy {edit_pol}")
            st.rerun()

    rows = [
        {
            "id": p.id,
            "template": p.template,
            "agent": p.agent or "(all)",
            "budget": p.budget_id or "—",
            "segment": p.segment_id or "—",
            "enabled": p.enabled,
            "params": json.dumps(p.params),
        }
        for p in store.list_policy_instances()
    ]
    st.dataframe(rows, use_container_width=True)

# ---- effective config preview -------------------------------------------- #
st.markdown("#### Effective governance config")
st.caption("What `build_governor` receives per agent on the next run.")
preview_agent = st.selectbox(
    "Preview for agent",
    ["research", "summarize", "planner", "researcher", "writer"],
)
effective = store.governance_config_for(preview_agent)
st.json(effective)

with st.expander("Which policies use a budget?"):
    st.markdown(
        """
| Policy | Needs budget? | When it runs |
|---|---|---|
| `cost_budget` | **Yes** — trips when spend ≥ limit | After each crossing (`observe`) |
| `pre_call_worst_case` | **Yes** — blocks call if worst-case would exceed limit | Before each LLM (`pre_call`) |
| `cost_guard` | **Yes** — nudge at 80% of limit | After each crossing |
| `step_cap` | No — uses `max_steps` param | After each crossing |
| `concurrency_cap` | No | Before each LLM |
| `tool_fix` | No | After tool crossings |
| `tool_output_cap` | No | After tool crossings |
| `progress_guard` | No | After crossings + clock |
| `context_compaction` | No | Before LLM |
| `output_runaway` | No | After LLM output |
"""
    )

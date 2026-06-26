"""Dashboard — agent runs, problematic runs with failure reason, and cost reporting (goal 4).

Read-only over the shared SQLite store, so it survives server/UI restarts (unlike the
in-memory ledger). Each A2A run handler writes a RunRecord; this page reads them back.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from tokenops.ui.store_client import get_store

st.set_page_config(page_title="TokenOps — Dashboard", layout="wide")
st.title("Run dashboard")
store = get_store()

runs = store.list_runs(limit=500)
if not runs:
    st.info("No runs yet. Start one from the Run pipeline page, then refresh.")
    st.stop()


def _usd(micros: int) -> float:
    return round(micros / 1_000_000, 6)


def _duration(r) -> float | None:
    return round(r.ended_at - r.started_at, 2) if r.ended_at else None


# ---- top-line cost reporting --------------------------------------------- #
total_cost = sum(r.cost_micros for r in runs)
problematic = [r for r in runs if r.problematic]
c1, c2, c3, c4 = st.columns(4)
c1.metric("Runs", len(runs))
c2.metric("Total cost", f"${_usd(total_cost):.4f}")
c3.metric("Problematic", len(problematic))
c4.metric("Avg $/run", f"${_usd(total_cost // max(1, len(runs))):.4f}")

# cost by agent
by_agent: dict[str, int] = {}
for r in runs:
    by_agent[r.agent] = by_agent.get(r.agent, 0) + r.cost_micros
st.subheader("Cost by agent")
st.bar_chart(pd.DataFrame({"cost_usd": {a: _usd(m) for a, m in by_agent.items()}}))

# ---- runs table ----------------------------------------------------------- #
st.subheader("Runs")
only_bad = st.toggle("Problematic only (halted / throttled / error)")
shown = problematic if only_bad else runs
table = pd.DataFrame([{
    "run_id": r.run_id, "agent": r.agent, "status": r.status,
    "cost_usd": _usd(r.cost_micros), "steps": r.steps,
    "duration_s": _duration(r), "halt_reason": r.halt_reason or "",
    "parent_run": r.parent_run or "",
} for r in shown])
st.dataframe(table, use_container_width=True, hide_index=True)

# ---- failure detail ------------------------------------------------------- #
if problematic:
    st.subheader("Failure detail")
    pick = st.selectbox("Problematic run", [r.run_id for r in problematic])
    r = store.get_run(pick)
    if r:
        st.error(f"**{r.status.upper()}** — {r.halt_reason or 'no reason recorded'}")
        st.write({
            "run_id": r.run_id, "agent": r.agent, "detector": r.detector,
            "cost_usd": _usd(r.cost_micros), "steps": r.steps,
            "task": r.task, "corpus_profile": r.corpus_profile,
            "parent_run": r.parent_run,
        })

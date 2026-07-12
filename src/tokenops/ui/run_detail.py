"""Shared run detail panel for Dashboard (and future pages)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from tokenops.control.models import RunRecord
from tokenops.control.store import Store


def _usd(micros: int) -> float:
    return round(micros / 1_000_000, 6)


def _duration(r: RunRecord) -> float | None:
    return round(r.ended_at - r.started_at, 2) if r.ended_at else None


def _status_banner(r: RunRecord) -> None:
    if r.status == "halted":
        # Intentional governance stop — not a crash.
        st.warning(
            f"**GOVERNANCE HALT** — {r.halt_reason or 'budget policy stopped the run'}"
        )
    elif r.status == "throttled":
        st.warning(f"**THROTTLED** — {r.halt_reason or 'no reason recorded'}")
    elif r.status == "completed":
        st.success(f"**COMPLETED** — ${_usd(r.cost_micros):.4f} accrued")
    elif r.status == "error":
        st.error(f"**ERROR** — {r.halt_reason or 'run failed'}")
    else:
        st.info(f"**{r.status.upper()}**")


def render_run_detail(store: Store, run: RunRecord) -> None:
    """Full run inspection: cost, halt reason, and governance trace for any run."""
    _status_banner(run)

    reg = store.get_run_registration(run.run_id)
    mode = reg.mode.value if reg else "—"

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Cost", f"${_usd(run.cost_micros):.4f}")
    c2.metric("Steps", run.steps)
    c3.metric("Duration (s)", _duration(run))
    c4.metric("Governance", mode)

    with st.expander("Run metadata", expanded=False):
        st.json(
            {
                "run_id": run.run_id,
                "agent": run.agent,
                "status": run.status,
                "detector": run.detector,
                "halt_reason": run.halt_reason,
                "parent_run": run.parent_run,
                "intent": reg.intent if reg else None,
                "task": (run.task or "")[:240],
                "dims": run.dims,
            }
        )

    st.subheader("Governance trace")
    events = run.governance_events or []
    if not events:
        st.caption("No governance actions recorded for this run.")
        return

    rows = []
    for ev in events:
        rows.append(
            {
                "policy": ev.get("policy", "—"),
                "kind": ev.get("kind", ""),
                "reason": ev.get("reason", ""),
                "steering": (ev.get("message") or "")[:120],
                "max_output": ev.get("max_output_tokens"),
            }
        )
    df = pd.DataFrame(rows)

    # Tight gold/black highlight for the governance mechanisms the demo is meant to show.
    highlight_policies = {"pre_call_worst_case", "cost_guard"}

    def _style_row(row: pd.Series) -> list[str]:
        policy = str(row.get("policy") or "")
        kind = str(row.get("kind") or "")
        if policy in highlight_policies or kind in ("halt", "throttle"):
            return [
                "background-color: rgba(201, 162, 39, 0.16);"
                if c in ("policy", "kind", "reason", "steering")
                else ""
                for c in df.columns
            ]
        return ["" for _ in df.columns]

    st.dataframe(
        df.style.apply(_style_row, axis=1),
        use_container_width=True,
        hide_index=True,
    )

    halts = [ev for ev in events if ev.get("kind") == "halt"]
    if halts:
        with st.expander("Halt detail", expanded=True):
            for ev in halts:
                st.markdown(f"**{ev.get('policy', '—')}** · `halt`")
                st.code(ev.get("reason", ""))

    steer = [ev for ev in events if ev.get("kind") in ("inject", "mutate")]
    if steer:
        with st.expander("Steering detail", expanded=any(ev.get("kind") == "inject" for ev in steer)):
            for ev in steer:
                st.markdown(f"**{ev.get('policy', '—')}** · `{ev.get('kind')}`")
                st.caption(ev.get("reason", ""))
                if ev.get("message"):
                    st.code(ev["message"])
                if ev.get("max_output_tokens") is not None:
                    st.caption(f"Output cap set to {ev['max_output_tokens']} tokens")

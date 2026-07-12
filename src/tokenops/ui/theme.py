"""Shared Streamlit styling — black + gold TokenOps look."""

from __future__ import annotations

import streamlit as st

GOLD = "#C9A227"
GOLD_DIM = "#8A7020"
INK = "#0A0A0A"
PANEL = "#121212"
MUTED = "#9A9588"


def inject_theme() -> None:
    st.markdown(
        f"""
        <style>
        .stApp {{
            background: linear-gradient(180deg, {INK} 0%, #0E0E0E 100%);
        }}
        [data-testid="stSidebar"] {{
            background-color: {PANEL};
            border-right: 1px solid #1F1F1F;
        }}
        [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 {{
            color: {GOLD};
        }}
        .tokenops-header {{
            padding: 0.25rem 0 1.25rem 0;
            border-bottom: 1px solid #222;
            margin-bottom: 1.25rem;
        }}
        .tokenops-title {{
            font-size: 1.75rem;
            font-weight: 700;
            letter-spacing: 0.04em;
            color: {GOLD};
            margin: 0;
        }}
        .tokenops-sub {{
            color: {MUTED};
            font-size: 0.9rem;
            margin-top: 0.35rem;
        }}
        .status-pill {{
            display: inline-block;
            padding: 0.15rem 0.55rem;
            border-radius: 999px;
            font-size: 0.75rem;
            font-weight: 600;
            letter-spacing: 0.03em;
            text-transform: uppercase;
        }}
        .status-on {{
            background: rgba(201, 162, 39, 0.15);
            color: {GOLD};
            border: 1px solid {GOLD_DIM};
        }}
        .status-off {{
            background: rgba(180, 60, 60, 0.12);
            color: #E07070;
            border: 1px solid #5A2020;
        }}
        div[data-testid="stChatMessage"] {{
            background-color: {PANEL};
            border: 1px solid #1E1E1E;
            border-radius: 12px;
        }}
        .stChatInput textarea {{
            border-color: {GOLD_DIM} !important;
        }}
        .stChatInput textarea:focus {{
            border-color: {GOLD} !important;
            box-shadow: 0 0 0 1px {GOLD} !important;
        }}
        [data-testid="stMetric"] {{
            background: {PANEL};
            border: 1px solid #1E1E1E;
            border-radius: 10px;
            padding: 0.65rem 0.85rem;
        }}
        [data-testid="stMetricLabel"] {{
            color: {MUTED} !important;
        }}
        [data-testid="stMetricValue"] {{
            color: {GOLD} !important;
        }}
        .stTabs [data-baseweb="tab-list"] {{
            gap: 0.35rem;
            border-bottom: 1px solid #222;
        }}
        .stTabs [data-baseweb="tab"] {{
            background: {PANEL};
            border-radius: 8px 8px 0 0;
            color: {MUTED};
            border: 1px solid transparent;
        }}
        .stTabs [aria-selected="true"] {{
            color: {GOLD} !important;
            border-color: {GOLD_DIM} !important;
            background: #181818 !important;
        }}
        [data-testid="stDataFrame"] {{
            border: 1px solid #1E1E1E;
            border-radius: 8px;
        }}
        .stExpander {{
            border: 1px solid #1E1E1E !important;
            border-radius: 8px !important;
            background: {PANEL} !important;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_header(*, subtitle: str) -> None:
    st.markdown(
        f"""
        <div class="tokenops-header">
            <p class="tokenops-title">TokenOps</p>
            <p class="tokenops-sub">{subtitle}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def page_shell(*, subtitle: str) -> None:
    """Header + theme for routed pages (``st.navigation`` — no ``set_page_config``)."""
    inject_theme()
    render_header(subtitle=subtitle)


def setup_page(*, page: str, subtitle: str, layout: str = "wide") -> None:
    """Standalone page entry (legacy multipage ``pages/`` folder)."""
    st.set_page_config(page_title=f"TokenOps — {page}", layout=layout)
    page_shell(subtitle=subtitle)


def status_pill(label: str, online: bool) -> str:
    css = "status-on" if online else "status-off"
    state = "online" if online else "offline"
    return f'<span class="status-pill {css}">{label} · {state}</span>'

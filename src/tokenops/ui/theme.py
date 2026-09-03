"""Shared Streamlit styling — light, minimalist TokenOps look."""

from __future__ import annotations

import streamlit as st

GOLD = "#A9762C"
GOLD_DIM = "#E3D3AE"
INK = "#1C1B17"
BG = "#FAFAF7"
PANEL = "#FFFFFF"
BORDER = "#E7E4DB"
MUTED = "#716E63"


def inject_theme() -> None:
    st.markdown(
        f"""
        <style>
        .stApp {{
            background: {BG};
        }}
        [data-testid="stSidebar"] {{
            background-color: {PANEL};
            border-right: 1px solid {BORDER};
        }}
        [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 {{
            color: {INK};
        }}
        [data-testid="stMarkdownContainer"] p, [data-testid="stMarkdownContainer"] li {{
            color: {INK};
        }}
        .tokenops-header {{
            padding: 0.25rem 0 1.25rem 0;
            border-bottom: 1px solid {BORDER};
            margin-bottom: 1.25rem;
        }}
        .tokenops-title {{
            font-size: 1.75rem;
            font-weight: 700;
            letter-spacing: 0.02em;
            color: {INK};
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
            background: #F5EBD3;
            color: {GOLD};
            border: 1px solid {GOLD_DIM};
        }}
        .status-off {{
            background: #FBEAEA;
            color: #B23B3B;
            border: 1px solid #EFC6C6;
        }}
        div[data-testid="stChatMessage"] {{
            background-color: {PANEL};
            border: 1px solid {BORDER};
            border-radius: 12px;
            box-shadow: 0 1px 2px rgba(28, 27, 23, 0.04);
        }}
        .stChatInput textarea {{
            border-color: {BORDER} !important;
        }}
        .stChatInput textarea:focus {{
            border-color: {GOLD} !important;
            box-shadow: 0 0 0 1px {GOLD} !important;
        }}
        [data-testid="stMetric"] {{
            background: {PANEL};
            border: 1px solid {BORDER};
            border-radius: 10px;
            padding: 0.65rem 0.85rem;
            box-shadow: 0 1px 2px rgba(28, 27, 23, 0.04);
        }}
        [data-testid="stMetricLabel"] {{
            color: {MUTED} !important;
        }}
        [data-testid="stMetricValue"] {{
            color: {INK} !important;
        }}
        .stTabs [data-baseweb="tab-list"] {{
            gap: 0.35rem;
            border-bottom: 1px solid {BORDER};
        }}
        .stTabs [data-baseweb="tab"] {{
            background: transparent;
            border-radius: 8px 8px 0 0;
            color: {MUTED};
            border: 1px solid transparent;
        }}
        .stTabs [aria-selected="true"] {{
            color: {GOLD} !important;
            border-color: {BORDER} !important;
            background: {PANEL} !important;
        }}
        [data-testid="stDataFrame"] {{
            border: 1px solid {BORDER};
            border-radius: 8px;
        }}
        .stExpander {{
            border: 1px solid {BORDER} !important;
            border-radius: 8px !important;
            background: {PANEL} !important;
            box-shadow: 0 1px 2px rgba(28, 27, 23, 0.04);
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

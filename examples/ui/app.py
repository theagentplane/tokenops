"""Bench Streamlit entry — Test Bench + Simulator + product Admin/Dashboard."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

import tokenops.ui as core_ui
from tokenops.env import load_env

load_env()

from tokenops.ui.theme import inject_theme

st.set_page_config(page_title="TokenOps", layout="wide", initial_sidebar_state="expanded")
inject_theme()

_BENCH_UI = Path(__file__).resolve().parent
_CORE_UI = Path(core_ui.__file__).resolve().parent

chat = st.Page(_BENCH_UI / "views/chat.py", title="Chat", default=True)
simulator = st.Page(_BENCH_UI / "views/simulator_view.py", title="Simulator")
dashboard = st.Page(_CORE_UI / "views/dashboard.py", title="Dashboard")
admin = st.Page(_CORE_UI / "views/admin.py", title="Admin")

st.navigation(
    {
        "": [chat, simulator, dashboard],
        "Configure": [admin],
    }
).run()

"""TokenOps product UI — Admin + Dashboard."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from tokenops.env import load_env

load_env()

from tokenops.ui.theme import inject_theme

st.set_page_config(page_title="TokenOps", layout="wide", initial_sidebar_state="expanded")
inject_theme()

_UI = Path(__file__).resolve().parent

dashboard = st.Page(_UI / "views/dashboard.py", title="Dashboard", default=True)
admin = st.Page(_UI / "views/admin.py", title="Admin")

st.navigation(
    {
        "": [dashboard],
        "Configure": [admin],
    }
).run()

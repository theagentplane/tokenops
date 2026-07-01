"""Shared Store handle for the Streamlit UIs — opens the same SQLite file the servers use."""

from __future__ import annotations

import os

import streamlit as st

from tokenops.control.store import Store


@st.cache_resource
def get_store() -> Store:
    """One Store per UI process (cached across reruns). Points at the same DB the A2A
    servers write to via the TOKENOPS_DB env var (default ``tokenops.db``).

    ``auto_seed=False`` — governance is seeded at deploy via ``make db-reseed`` or
    ``Store.seed_default_governance_if_empty`` on first server start; the Admin UI should
    not re-seed over user edits."""
    return Store(os.environ.get("TOKENOPS_DB", "tokenops.db"), auto_seed=False)


def clear_store_cache() -> None:
    """Drop the cached Store (e.g. after external ``db-reset`` script)."""
    get_store.clear()

from __future__ import annotations

from pathlib import Path

import streamlit as st
import yaml

from tokenops.env import load_env

load_env()

from tokenops.a2a.client import check_health_sync, submit_task_sync
from tokenops.config import AppConfig, list_presets, load_config, save_config
from tokenops.config.loader import PRESETS_DIR

st.set_page_config(page_title="TokenOps Test Bench", layout="wide")
st.title("Two-Agent Test Bench")
st.caption("Research agent delegates to summarize agent over A2A. UI calls research only.")


def cfg_from_session() -> AppConfig:
    if "config" not in st.session_state:
        st.session_state.config = load_config()
    return st.session_state.config


def render_sidebar() -> AppConfig:
    cfg = cfg_from_session()
    st.sidebar.header("Configuration")

    presets = list_presets()
    preset_names = [p.stem for p in presets]
    if preset_names:
        choice = st.sidebar.selectbox("Load preset", ["—"] + preset_names)
        if choice != "—":
            st.session_state.config = load_config(PRESETS_DIR / f"{choice}.yaml")
            cfg = st.session_state.config

    cfg.task = st.sidebar.text_area("Task", cfg.task, height=80)
    cfg.corpus_profile = st.sidebar.selectbox(
        "Corpus profile",
        ["healthy", "leak"],
        index=0 if cfg.corpus_profile == "healthy" else 1,
        help="healthy: full results. leak: same sources, garbled/truncated (simulates bad crawl).",
    )

    st.sidebar.subheader("Research agent")
    cfg.research.url = st.sidebar.text_input("Research URL", cfg.research.url)
    cfg.research.summarize_url = st.sidebar.text_input("Summarize URL (delegation)", cfg.research.summarize_url)
    cfg.research.framework = st.sidebar.selectbox(
        "Framework", ["native", "langchain"], index=0 if cfg.research.framework == "native" else 1
    )
    cfg.research.provider = st.sidebar.text_input("Provider", cfg.research.provider)
    cfg.research.model = st.sidebar.text_input("Model", cfg.research.model)
    cfg.research.port = st.sidebar.number_input("Port", value=int(cfg.research.port), step=1)
    cfg.research.max_steps = st.sidebar.number_input("Max steps", value=int(cfg.research.max_steps), step=1)
    cfg.research.satisfaction_threshold = st.sidebar.slider(
        "Satisfaction threshold", 0.0, 1.0, float(cfg.research.satisfaction_threshold)
    )

    st.sidebar.subheader("Summarize agent")
    cfg.summarize.url = st.sidebar.text_input("Summarize URL", cfg.summarize.url)
    cfg.summarize.framework = st.sidebar.selectbox(
        "Summarize framework",
        ["native", "langchain"],
        index=0 if cfg.summarize.framework == "native" else 1,
    )
    cfg.summarize.provider = st.sidebar.text_input("Summarize provider", cfg.summarize.provider)
    cfg.summarize.model = st.sidebar.text_input("Summarize model", cfg.summarize.model)
    cfg.summarize.port = st.sidebar.number_input("Summarize port", value=int(cfg.summarize.port), step=1)

    if st.sidebar.button("Save config YAML"):
        out = Path("saved-config.yaml")
        save_config(cfg, out)
        st.sidebar.success(f"Saved {out}")

    st.sidebar.markdown("---")
    st.sidebar.markdown("**Server health**")
    research_ok = check_health_sync(cfg.research.url)
    summarize_ok = check_health_sync(cfg.summarize.url)
    st.sidebar.write(f"Research: {'online' if research_ok else 'offline'}")
    st.sidebar.write(f"Summarize: {'online' if summarize_ok else 'offline'}")
    st.sidebar.caption("Restart servers after changing framework/model.")

    return cfg


def main() -> None:
    cfg = render_sidebar()

    col1, col2 = st.columns([1, 3])
    with col1:
        run = st.button("Run pipeline", type="primary", use_container_width=True)

    if run:
        if not check_health_sync(cfg.research.url):
            st.error("Research server is offline. Start it with `make research-server`.")
            return
        with st.spinner("Running research → summarize via A2A..."):
            try:
                st.session_state.last_result = submit_task_sync(
                    cfg.research.url, cfg.task, cfg.corpus_profile
                )
            except Exception as exc:
                st.error(f"Run failed: {exc}")
                return

    if "last_result" not in st.session_state:
        return

    result = st.session_state.last_result
    st.success("Done")
    st.subheader("Summary")
    st.write(result.summary)

    with st.expander("Findings", expanded=False):
        st.json([f.to_dict() for f in result.findings])

    st.subheader("Step log")
    st.caption("Each model call, search, and A2A delegation during the run.")
    if result.steps:
        st.dataframe([s.display_row() for s in result.steps], use_container_width=True)
    else:
        st.info("No steps recorded.")

    st.subheader("Token usage")
    st.json(result.token_usage.to_dict())

    st.subheader("Raw response")
    st.code(yaml.safe_dump(result.to_dict(), sort_keys=False), language="yaml")


if __name__ == "__main__":
    main()

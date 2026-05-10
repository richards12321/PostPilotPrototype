"""Streamlit entry point.

Routes to the right view based on st.session_state.stage and mode.
Everything kicks off from here.

Run with:
    streamlit run app.py
"""

from __future__ import annotations

import streamlit as st

from database import db
from views import (
    candidate_intro,
    candidate_results,
    landing,
    layer1,
    layer2,
    layer3,
    recruiter_dashboard,
)
from views.state import init_session_state


def main() -> None:
    st.set_page_config(
        page_title="Capgemini Invent: Consulting Assessment",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="collapsed",
    )

    # Initialize DB once per process
    if "db_initialized" not in st.session_state:
        freshly_seeded = db.init_db()
        st.session_state.db_initialized = True
        if freshly_seeded:
            print("=" * 60)
            print("First-time setup complete.")
            print(f"Default recruiter login: {db.DEFAULT_RECRUITER_USERNAME} / {db.DEFAULT_RECRUITER_PASSWORD}")
            print("=" * 60)

    init_session_state()

    mode = st.session_state.mode
    stage = st.session_state.stage

    # Recruiter flow
    if mode == "recruiter" and st.session_state.recruiter_authed:
        recruiter_dashboard.render()
        return

    # Candidate flow (only once they've been created in DB)
    if mode == "candidate" and st.session_state.candidate_id:
        if stage == "intro":
            candidate_intro.render()
        elif stage == "layer1":
            layer1.render()
        elif stage == "layer2":
            layer2.render()
        elif stage == "layer3":
            layer3.render()
        elif stage in ("results", "done"):
            candidate_results.render()
        else:
            # unknown stage, fall back to landing
            candidate_intro.render()
        return

    # Default: landing page
    landing.render()


if __name__ == "__main__":
    main()

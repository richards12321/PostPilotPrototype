"""Candidate intro page: welcome + overview."""

from __future__ import annotations

import streamlit as st

from .state import advance_stage


def render() -> None:
    st.title(f"Welcome, {st.session_state.candidate_name.split()[0]}")

    st.markdown(
        """
        Over the next ~60 minutes, you'll complete three short exercises that help us
        understand how you think, solve problems, and communicate.
        
        **Layer 1: Cognitive Assessment** (~30 minutes)  
        30 timed reasoning questions across logical, numerical, and verbal themes.
        
        **Layer 2: Staffing Simulation** (~20 minutes)  
        An 8-week firm simulation where you act as a resource manager assigning
        consultants to projects under real-world constraints.
        
        **Layer 3: AI-Led Interview** (~16 minutes)  
        Four voice-recorded questions with a live follow-up for each.
        
        ---
        
        Your answers are saved as you go. If you accidentally close the tab, you can
        return and resume by entering the same email. When you finish, you'll receive
        personalized feedback on your performance.
        """
    )

    st.info(
        "Find a quiet spot, make sure your microphone works, and give yourself "
        "uninterrupted time. Good luck."
    )

    if st.button("Begin Layer 1", type="primary", use_container_width=True):
        advance_stage("layer1")

"""Candidate results page shown after Layer 3.

Computes final scores + generates candidate and recruiter-facing feedback.
Displays candidate-facing summary only. Top-fit and recruiter summary are
hidden from candidates.
"""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from assessment_logic.feedback_generator import (
    generate_candidate_feedback,
    generate_recruiter_summary,
)
from assessment_logic.layer1_logic import aggregate_layer1
from assessment_logic.layer2_logic import aggregate_layer2
from assessment_logic.layer3_logic import aggregate_layer3
from assessment_logic.scoring_matrix import assemble_final_scores
from database import db


def render() -> None:
    candidate_id = st.session_state.candidate_id

    # Compute once, cache in DB
    existing = db.get_final_score(candidate_id)
    if not existing and not st.session_state.get("final_result_computed"):
        _compute_and_persist(candidate_id)
        st.session_state.final_result_computed = True
        existing = db.get_final_score(candidate_id)

    if not existing:
        st.error("Results could not be computed. Please contact support.")
        return

    _render_candidate_view(existing)


def _compute_and_persist(candidate_id: str) -> None:
    with st.spinner("Computing your results..."):
        # Layer 1: recompute from DB in case session state is stale
        l1_rows = db.get_layer1_results(candidate_id)
        theme_totals = {"logical": [0, 0], "numerical": [0, 0], "verbal": [0, 0]}
        for r in l1_rows:
            theme_totals[r["theme"]][0] += 1
            theme_totals[r["theme"]][1] += int(r["is_correct"])
        theme_scores = {
            t: (correct / total * 100) if total > 0 else 0
            for t, (total, correct) in theme_totals.items()
        }
        layer1, l1_comp = aggregate_layer1(theme_scores)

        # Layer 2: read the simulation result and rehydrate state for competency calc
        l2_sim = db.get_layer2_simulation(candidate_id)
        if l2_sim:
            import json
            from assessment_logic.layer2_logic import load_scenario
            final_state = json.loads(l2_sim["final_state_json"])
            scenario = load_scenario()
            layer2, l2_comp = aggregate_layer2(final_state, scenario)
        else:
            layer2 = 0.0
            l2_comp = {"competency_strategic": 0.0, "competency_adaptability": 0.0}

        # Layer 3
        l3_rows = db.get_layer3_results(candidate_id)
        competency_scores = [
            {
                "competency_key": r["competency_key"],
                "competency_id": r["competency_id"],
                "score": r["competency_score"] if r["competency_score"] is not None else 0,
            } for r in l3_rows
        ]
        layer3, l3_comp = aggregate_layer3(competency_scores)

        # Pull AI flags from session state (set by Layer 1 finish and Layer 2 finalize).
        # These are informational only and don't affect any score.
        ai_flags = {
            "ai_flag_logical": int(bool(st.session_state.get("l1_ai_flag_logical", False))),
            "ai_flag_numerical": int(bool(st.session_state.get("l1_ai_flag_numerical", False))),
            "ai_flag_verbal": int(bool(st.session_state.get("l1_ai_flag_verbal", False))),
            "ai_flag_layer2": int(bool(st.session_state.get("l2_ai_flag", False))),
        }

        # Assemble (placeholder feedback first, then generate)
        draft = assemble_final_scores(
            candidate_id=candidate_id,
            layer1=layer1, layer2=layer2, layer3=layer3,
            l1_comp=l1_comp, l2_comp=l2_comp, l3_comp=l3_comp,
            candidate_feedback="",
            recruiter_summary="",
            ai_flags=ai_flags,
        )

    with st.spinner("Generating personalized feedback..."):
        candidate_feedback = generate_candidate_feedback(draft)
    with st.spinner("Finalizing..."):
        recruiter_summary = generate_recruiter_summary(draft)

    draft["candidate_feedback"] = candidate_feedback
    draft["recruiter_summary"] = recruiter_summary
    db.save_final_score(draft)
    db.mark_complete(candidate_id)


def _render_candidate_view(scores: dict) -> None:
    st.title(f"Your Assessment Results")
    st.caption(f"Thanks for completing the assessment, {st.session_state.candidate_name.split()[0]}.")

    # Top-line summary
    st.subheader("Overall score")
    cols = st.columns(4)
    cols[0].metric("Overall", f"{scores['overall_score']:.0f}")
    cols[1].metric("Layer 1", f"{scores['layer1_score']:.0f}")
    cols[2].metric("Layer 2", f"{scores['layer2_score']:.0f}")
    cols[3].metric("Layer 3", f"{scores['layer3_score']:.0f}")

    st.divider()

    # Bar chart of the three layers
    st.subheader("Layer breakdown")
    bar = go.Figure()
    bar.add_trace(go.Bar(
        x=["Layer 1 (Cognitive)", "Layer 2 (Staffing)", "Layer 3 (Interview)"],
        y=[scores["layer1_score"], scores["layer2_score"], scores["layer3_score"]],
        marker_color=["#3B82F6", "#10B981", "#F59E0B"],
        text=[f"{scores['layer1_score']:.0f}",
              f"{scores['layer2_score']:.0f}",
              f"{scores['layer3_score']:.0f}"],
        textposition="auto",
    ))
    bar.update_layout(
        yaxis_range=[0, 100],
        yaxis_title="Score",
        height=350,
        margin=dict(t=20, b=20),
    )
    st.plotly_chart(bar, use_container_width=True)

    # Competency radar
    st.subheader("Competency profile")
    comp_labels = [
        "Analytical", "Numerical", "Verbal",
        "Strategic", "Adaptability (sim)",
        "Growth Mindset", "Adaptability (interview)",
        "Collaboration", "Self-Reflection",
    ]
    comp_values = [
        scores.get("competency_analytical") or 0,
        scores.get("competency_numerical") or 0,
        scores.get("competency_verbal") or 0,
        scores.get("competency_strategic") or 0,
        scores.get("competency_adaptability") or 0,
        scores.get("competency_l3_growth_mindset") or 0,
        scores.get("competency_l3_adaptability") or 0,
        scores.get("competency_l3_collaboration") or 0,
        scores.get("competency_l3_self_reflection") or 0,
    ]
    radar = go.Figure()
    radar.add_trace(go.Scatterpolar(
        r=comp_values + [comp_values[0]],
        theta=comp_labels + [comp_labels[0]],
        fill="toself",
        line_color="#6366F1",
        name="You",
    ))
    radar.update_layout(
        polar=dict(radialaxis=dict(range=[0, 100], visible=True)),
        showlegend=False,
        height=420,
        margin=dict(t=40, b=20),
    )
    st.plotly_chart(radar, use_container_width=True)

    st.divider()

    # LLM-generated feedback
    st.subheader("Your developmental feedback")
    if scores.get("candidate_feedback"):
        st.markdown(scores["candidate_feedback"])
    else:
        st.info("Personalized feedback is still being generated. Please refresh in a moment.")

    st.divider()
    st.caption(
        "Your results have been recorded. A member of the recruitment team will "
        "be in touch with next steps."
    )

    st.success(
        "**The assessment is complete. You can close this page now.**"
    )

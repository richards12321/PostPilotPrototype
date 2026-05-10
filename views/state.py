"""Shared helpers for Streamlit session state and routing.

We use DB-backed stage tracking so refreshes don't lose progress.
Session state is rebuilt from the DB on resume.

Layer 2 resume note: the firm simulation is continuous and intra-layer
state isn't checkpointed to DB. If a candidate refreshes mid-Layer-2
they'll restart Layer 2 from Week 1. Once they finish Layer 2, the
final state is persisted and they can resume into Layer 3.
"""

from __future__ import annotations

import streamlit as st

from database import db

STAGES = ["intro", "layer1", "layer2", "layer3", "results", "done"]


def init_session_state() -> None:
    defaults = {
        "mode": None,                # 'candidate' or 'recruiter'
        "candidate_id": None,
        "candidate_name": None,
        "candidate_email": None,
        "stage": "landing",
        "recruiter_authed": False,

        # Layer 1 progress
        "l1_theme_idx": 0,
        "l1_question_idx": 0,
        "l1_questions_cache": {},       # theme -> list[Question]
        "l1_theme_scores": {},          # theme -> score (used for final results)
        "l1_question_started_at": None,

        # Layer 2 progress (simulation)
        "l2_started": False,
        "l2_started_at": None,
        "l2_state": None,                # the firm simulation state dict

        # Layer 3 progress (continuous voice flow)
        "l3_started": False,
        "l3_main_questions": [],
        "l3_turns": [],                  # flat turn list (main, followup, ...)
        "l3_turn_idx": 0,
        "l3_answer_scores": [],
        "l3_started_at": None,           # set when first question is spoken
        "l3_finished": False,

        # Results cache
        "final_result_computed": False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def reset_candidate_state() -> None:
    """Wipe all candidate-specific session state."""
    keys = [
        "mode", "candidate_id", "candidate_name", "candidate_email", "stage",
        "l1_theme_idx", "l1_question_idx", "l1_questions_cache", "l1_theme_scores",
        "l1_question_started_at",
        "l2_started", "l2_started_at", "l2_state",
        "l3_started", "l3_main_questions", "l3_turns", "l3_turn_idx",
        "l3_answer_scores", "l3_started_at", "l3_finished",
        "final_result_computed",
    ]
    # Also strip any per-turn / per-theme dynamic keys.
    dynamic_prefixes = [
        "l3_transcript_turn_", "l3_transcribed_id_turn_",
        "l3_main_transcript_", "l3_followup_meta_",
        "l3_spoken_", "l3_speak_started_",
        "l1_theme_started_at_", "l1_ai_flag_",
        "l2_ai_flag",
    ]
    for k in list(st.session_state.keys()):
        if any(k.startswith(p) or k == p for p in dynamic_prefixes):
            del st.session_state[k]
    for k in keys:
        if k in st.session_state:
            del st.session_state[k]
    init_session_state()


def resume_from_db(candidate: dict) -> None:
    """Rebuild session state from DB data so the candidate picks up where they left off."""
    cid = candidate["candidate_id"]
    st.session_state.mode = "candidate"
    st.session_state.candidate_id = cid
    st.session_state.candidate_name = candidate["full_name"]
    st.session_state.candidate_email = candidate["email"]
    st.session_state.stage = candidate["current_stage"]

    # Layer 1: rehydrate theme_scores from answered questions
    l1_rows = db.get_layer1_results(cid)
    theme_counts: dict = {"logical": 0, "numerical": 0, "verbal": 0}
    theme_correct: dict = {"logical": 0, "numerical": 0, "verbal": 0}
    for r in l1_rows:
        theme_counts[r["theme"]] += 1
        theme_correct[r["theme"]] += int(r["is_correct"])
    st.session_state.l1_theme_scores = {
        t: (theme_correct[t] / 10 * 100) for t in theme_counts if theme_counts[t] >= 10
    }
    # figure out which theme the candidate is on
    from assessment_logic.layer1_logic import THEMES
    for idx, theme in enumerate(THEMES):
        if theme_counts[theme] < 10:
            st.session_state.l1_theme_idx = idx
            st.session_state.l1_question_idx = theme_counts[theme]
            break
    else:
        st.session_state.l1_theme_idx = len(THEMES)
        st.session_state.l1_question_idx = 0

    # Layer 2: simulation is not checkpointed mid-layer. If a final result
    # exists in the DB, the candidate already finished Layer 2, keep them
    # past the L2 stage. If not, they'll restart the sim from Week 1.
    if db.has_layer2_simulation(cid):
        st.session_state.l2_started = True
        # The state dict isn't carried (sim is done); just ensure the view
        # doesn't try to re-run it. The view handles "already saved" by
        # advancing past it.
    else:
        st.session_state.l2_started = False
        st.session_state.l2_state = None

    # Layer 3: rehydrate completed competencies. With the v7 turn model,
    # each completed competency consumes 2 turns (main + followup). If the
    # candidate refreshes mid-Layer-3, we restart Layer 3 from the next
    # un-scored competency (its 'main' turn). Mid-competency state isn't
    # persisted; that turn would restart from its main question.
    l3_rows = db.get_layer3_results(cid)
    st.session_state.l3_answer_scores = [
        {
            "competency_key": r["competency_key"],
            "competency_id": r["competency_id"],
            "score": r["competency_score"] if r["competency_score"] is not None else 0,
            "scripted_flag": bool(r.get("scripted_flag")) if isinstance(r, dict) else bool(r["scripted_flag"]),
        } for r in l3_rows
    ]
    completed = len(l3_rows)
    # Each completed competency is 2 turns (main + followup).
    st.session_state.l3_turn_idx = completed * 2
    st.session_state.l3_turns = []  # rebuild on next render
    st.session_state.l3_finished = False
    if l3_rows:
        st.session_state.l3_started = True


def advance_stage(new_stage: str) -> None:
    st.session_state.stage = new_stage
    if st.session_state.candidate_id:
        db.set_stage(st.session_state.candidate_id, new_stage)
    st.rerun()

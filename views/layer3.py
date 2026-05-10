"""Layer 3 view: AI-led structured behavioral interview.

Continuous voice flow. The interview is a single conversation:
the AI speaks a question, candidate records their answer, the system
silently transcribes it and either generates a follow-up (and asks it
out loud) or moves to the next competency. No Continue buttons between
exchanges. The candidate's only inputs during the interview are:
start recording, stop recording.

Structure:
  - 4 competencies, each with a main question + one targeted follow-up
  - 8 turns total (main, followup, main, followup, ...)
  - 16-minute total interview clock
  - 120-second per-answer recording cap
  - Pulsating/rotating orb shows AI speaking vs listening vs idle

Scoring per competency happens after the follow-up answer is captured.
On total time-out, the in-flight competency is scored with whatever
was captured; remaining competencies get score=0.
"""

from __future__ import annotations

import time
import uuid

import streamlit as st
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh

from assessment_logic.layer3_logic import (
    COMPETENCY_COUNT,
    generate_followup,
    load_main_questions,
    score_competency,
)
from assessment_logic.llm_client import transcribe_audio
from assessment_logic.recording_cap import render_recording_cap
from assessment_logic.tts import speak
from database import db

from .state import advance_stage

# st.audio_input is built into Streamlit and records at 16kHz mono by default,
# which is exactly what gpt-4o-mini-transcribe expects.
MIC_AVAILABLE = hasattr(st, "audio_input")

# Total interview budget (seconds). 16 min = 960s.
TOTAL_INTERVIEW_SECONDS = 16 * 60

# Per-answer recording cap (seconds).
PER_ANSWER_CAP_SECONDS = 120


# ---------------------------------------------------------------------------
# Public render entry point
# ---------------------------------------------------------------------------

def render() -> None:
    candidate_id = st.session_state.candidate_id

    if not st.session_state.get("l3_started", False):
        _intro()
        return

    # Lazy-load the per-candidate question list and build the turn schedule.
    if not st.session_state.l3_main_questions:
        st.session_state.l3_main_questions = load_main_questions(candidate_id)

    if not st.session_state.get("l3_turns"):
        _build_turn_list()

    # Final-screen guard: once we've completed all turns, finish up.
    if st.session_state.get("l3_finished"):
        _finish_layer()
        return

    # Total-time enforcement (only after the very first turn has started).
    if st.session_state.get("l3_started_at") is not None:
        elapsed = time.time() - st.session_state.l3_started_at
        if elapsed >= TOTAL_INTERVIEW_SECONDS:
            _handle_time_expiry(candidate_id)
            return

    _render_current_turn(candidate_id)


# ---------------------------------------------------------------------------
# Intro / outro
# ---------------------------------------------------------------------------

def _intro() -> None:
    st.title("Layer 3: AI-Led Interview")
    st.markdown(
        f"""
        You'll have a short voice conversation with an AI interviewer covering
        **{COMPETENCY_COUNT} competencies**: Growth Driven Mindset, Adaptability,
        Collaboration, and Self-Reflection. For each one, you'll get one
        question and one follow-up.

        **How it works:**
        1. The AI reads a question out loud.
        2. You click the microphone, answer, and click stop when done.
        3. The system silently transcribes your answer and the AI continues.
           Either it asks a follow-up, or it moves on to the next competency.
        4. There are no Continue buttons. The conversation flows on its own.

        **Time:**
        - Total interview: **16 minutes**, one continuous timer.
        - Each individual answer is capped at **2 minutes** (recording auto-stops).

        **Tips:**
        - Use concrete, specific examples.
        - It's fine to pause and think before you answer.
        - Don't rush. Clarity beats speed.
        - Make sure your speakers or headphones are on.

        If transcription fails for any reason, you can type your answer
        instead. There's a "Replay question" button if you missed what was said.
        """
    )

    if not MIC_AVAILABLE:
        st.warning(
            "The voice recorder component isn't available. You'll be able to "
            "type your answers instead."
        )

    if st.button("Begin Layer 3", type="primary", use_container_width=True):
        st.session_state.l3_started = True
        # We don't start the total timer yet. It starts on the first
        # actual question render (see _render_current_turn).
        st.session_state.l3_started_at = None
        st.rerun()


def _finish_layer() -> None:
    st.title("Layer 3 Complete")
    st.success(
        "You've completed all three layers. On the next screen you'll see your "
        "full results and personalized feedback."
    )

    if st.button("See my results", type="primary", use_container_width=True):
        advance_stage("results")


# ---------------------------------------------------------------------------
# Turn schedule construction
# ---------------------------------------------------------------------------

def _build_turn_list() -> None:
    """Build the flat list of turns from the loaded competency questions.

    Each turn is a dict:
      {"kind": "main" | "followup", "comp_idx": int, "text": str | None}
    Followup text is filled in after the main answer is captured.
    """
    turns = []
    for i, comp in enumerate(st.session_state.l3_main_questions):
        turns.append({"kind": "main",     "comp_idx": i, "text": comp["question"]})
        turns.append({"kind": "followup", "comp_idx": i, "text": None})
    st.session_state.l3_turns = turns
    st.session_state.l3_turn_idx = 0


def _total_turns() -> int:
    return len(st.session_state.l3_turns or [])


# ---------------------------------------------------------------------------
# Per-turn render
# ---------------------------------------------------------------------------

def _render_current_turn(candidate_id: str) -> None:
    turns = st.session_state.l3_turns
    turn_idx = st.session_state.l3_turn_idx

    if turn_idx >= len(turns):
        # No more turns. Mark finished.
        st.session_state.l3_finished = True
        st.rerun()
        return

    turn = turns[turn_idx]
    comp = st.session_state.l3_main_questions[turn["comp_idx"]]
    question_text = turn["text"] or "Can you tell me a bit more about that?"

    # Tick the clock so the header timer counts down live.
    st_autorefresh(interval=1000, key=f"l3_tick_{turn_idx}")

    _render_header(turn_idx, turn, comp)
    _render_orb(_orb_state(turn_idx))

    st.markdown(f"### {comp['competency_name']}")
    if turn["kind"] == "followup":
        st.caption("Follow-up")
    st.info(question_text)

    # Speak the question once per turn (autoplay), then never again on
    # subsequent reruns. The Replay button stays available.
    spoken_key = f"l3_spoken_{turn_idx}"
    autoplay = not st.session_state.get(spoken_key, False)
    speak(question_text, autoplay=autoplay)
    if autoplay:
        st.session_state[spoken_key] = True
        # Start the total interview timer the first time we speak something.
        if st.session_state.get("l3_started_at") is None:
            # Add ~3 seconds to roughly account for the spoken duration of
            # the first question (browser-side TTS doesn't give us a precise
            # finished-speaking callback).
            st.session_state.l3_started_at = time.time() + 3.0

    # Recording widget (or typed fallback).
    _render_recording_widget(candidate_id, turn_idx, turn, comp)


def _render_header(turn_idx: int, turn: dict, comp: dict) -> None:
    comp_idx = turn["comp_idx"]
    total_turns = _total_turns()

    col1, col2 = st.columns([3, 1])
    with col1:
        st.markdown(
            f"**Layer 3: Question {comp_idx + 1} of {COMPETENCY_COUNT} "
            f"({turn['kind']})**"
        )
        progress_val = (turn_idx) / total_turns if total_turns > 0 else 0.0
        st.progress(progress_val, text=f"Turn {turn_idx + 1} of {total_turns}")

    # Total time remaining
    started_at = st.session_state.get("l3_started_at")
    if started_at is not None:
        remaining = max(0, int(TOTAL_INTERVIEW_SECONDS - (time.time() - started_at)))
    else:
        remaining = TOTAL_INTERVIEW_SECONDS
    mins, secs = divmod(remaining, 60)
    green_cut = TOTAL_INTERVIEW_SECONDS // 3
    yellow_cut = TOTAL_INTERVIEW_SECONDS // 6
    color = "🟢" if remaining > green_cut else ("🟡" if remaining > yellow_cut else "🔴")
    with col2:
        st.metric("Interview time left", f"{color} {mins:02d}:{secs:02d}")


# ---------------------------------------------------------------------------
# Recording + auto-advance
# ---------------------------------------------------------------------------

def _render_recording_widget(
    candidate_id: str, turn_idx: int, turn: dict, comp: dict,
) -> None:
    transcript_key = f"l3_transcript_turn_{turn_idx}"
    audio_done_key = f"l3_transcribed_id_turn_{turn_idx}"

    if MIC_AVAILABLE:
        st.markdown("**Record your answer (up to 2 minutes):**")
        try:
            audio_file = st.audio_input(
                "Click the microphone to start, click again to stop.",
                sample_rate=16000,
                key=f"mic_turn_{turn_idx}",
                label_visibility="collapsed",
            )
        except TypeError:
            # Older Streamlit without sample_rate support.
            audio_file = st.audio_input(
                "Click the microphone to start, click again to stop.",
                key=f"mic_turn_{turn_idx}",
                label_visibility="collapsed",
            )

        # Hard cap at 2 minutes (auto-stops the recorder client-side).
        render_recording_cap(max_seconds=PER_ANSWER_CAP_SECONDS)

        if audio_file is not None:
            audio_bytes = audio_file.getvalue()
            fingerprint = (
                (audio_file.file_id, len(audio_bytes))
                if hasattr(audio_file, "file_id")
                else (id(audio_file), len(audio_bytes))
            )
            if st.session_state.get(audio_done_key) != fingerprint:
                st.session_state[audio_done_key] = fingerprint
                with st.spinner("Processing..."):
                    try:
                        transcript = transcribe_audio(audio_bytes, filename="recording.wav")
                        if not transcript:
                            raise ValueError("Empty transcript, recording may have been silent.")
                        st.session_state[transcript_key] = transcript
                        _on_answer_captured(candidate_id, turn_idx, turn, comp, transcript)
                        return
                    except Exception as e:
                        st.error(
                            f"Transcription failed: {type(e).__name__}: {e}\n\n"
                            "Type your answer below as a fallback."
                        )

    with st.expander("Or type your answer instead"):
        typed = st.text_area(
            "Type your answer",
            key=f"typed_turn_{turn_idx}",
            height=180,
        )
        if st.button("Submit typed answer", key=f"submit_typed_turn_{turn_idx}"):
            if typed.strip():
                st.session_state[transcript_key] = typed.strip()
                _on_answer_captured(candidate_id, turn_idx, turn, comp, typed.strip())
            else:
                st.warning("Please enter an answer first.")


def _on_answer_captured(
    candidate_id: str, turn_idx: int, turn: dict, comp: dict, transcript: str,
) -> None:
    """Branch on whether the captured answer was a main or follow-up."""
    if turn["kind"] == "main":
        # Stash the main transcript, generate a follow-up, fill in the next
        # turn's text, and advance.
        st.session_state[f"l3_main_transcript_{turn['comp_idx']}"] = transcript
        with st.spinner("Generating a follow-up question..."):
            followup = generate_followup(
                main_question=comp["question"],
                transcript=transcript,
                competency_name=comp["competency_name"],
                followup_goal=comp["followup_goal"],
            )
        # Fill in the next turn (the follow-up for this competency).
        next_turn = st.session_state.l3_turns[turn_idx + 1]
        next_turn["text"] = followup.get("question") or "Can you walk me through what you personally did?"
        # Stash the followup metadata for scoring later.
        st.session_state[f"l3_followup_meta_{turn['comp_idx']}"] = {
            "bucket": followup.get("bucket"),
            "question": next_turn["text"],
        }
        st.session_state.l3_turn_idx = turn_idx + 1
        st.rerun()
        return

    # turn['kind'] == 'followup': we now have main + follow-up answers. Score.
    comp_idx = turn["comp_idx"]
    main_transcript = st.session_state.get(f"l3_main_transcript_{comp_idx}", "")
    followup_meta = st.session_state.get(f"l3_followup_meta_{comp_idx}") or {}

    with st.spinner("Scoring..."):
        result = score_competency(
            main_question=comp["question"],
            main_transcript=main_transcript,
            followup_question=followup_meta.get("question", ""),
            followup_transcript=transcript,
            competency_name=comp["competency_name"],
            followup_goal=comp["followup_goal"],
        )

    main_dur = min(120.0, len(main_transcript.split()) / 2.5) if main_transcript else 0.0
    fu_dur = min(120.0, len(transcript.split()) / 2.5) if transcript else 0.0

    db.save_layer3_result(
        candidate_id=candidate_id,
        competency_order=comp_idx + 1,
        competency_id=comp["competency_id"],
        competency_key=comp["competency_key"],
        competency_name=comp["competency_name"],
        main_question=comp["question"],
        main_transcript=main_transcript,
        main_audio_duration_seconds=main_dur,
        followup_bucket=followup_meta.get("bucket"),
        followup_question=followup_meta.get("question"),
        followup_transcript=transcript,
        followup_audio_duration_seconds=fu_dur,
        competency_score=result["score"],
        scripted_flag=result["scripted_flag"],
        rationale=result["rationale"],
    )

    st.session_state.l3_answer_scores.append({
        "competency_key": comp["competency_key"],
        "competency_id": comp["competency_id"],
        "score": result["score"],
        "scripted_flag": result["scripted_flag"],
    })

    # Advance to the next turn (or finish).
    next_turn_idx = turn_idx + 1
    if next_turn_idx >= _total_turns():
        st.session_state.l3_finished = True
    else:
        st.session_state.l3_turn_idx = next_turn_idx
    st.rerun()


# ---------------------------------------------------------------------------
# Total-time expiry handling
# ---------------------------------------------------------------------------

def _handle_time_expiry(candidate_id: str) -> None:
    """Called when the 16-min interview clock hits zero.

    The currently-in-progress competency is scored with whatever's been
    captured so far. Any later competencies that haven't been touched yet
    get a zero row with rationale 'time expired'. Then we finish.
    """
    if st.session_state.get("l3_finished"):
        return

    turns = st.session_state.l3_turns or []
    main_qs = st.session_state.l3_main_questions
    already_scored = {
        s.get("competency_key") for s in st.session_state.l3_answer_scores
    }

    # Score the in-flight competency (if any) with what we've got.
    current_idx = st.session_state.l3_turn_idx
    if current_idx < len(turns):
        current = turns[current_idx]
        comp = main_qs[current["comp_idx"]]
        if comp["competency_key"] not in already_scored:
            comp_idx = current["comp_idx"]
            main_transcript = st.session_state.get(f"l3_main_transcript_{comp_idx}", "")
            followup_meta = st.session_state.get(f"l3_followup_meta_{comp_idx}") or {}
            # Whichever transcript field we have for the current turn:
            transcript_key = f"l3_transcript_turn_{current_idx}"
            captured = st.session_state.get(transcript_key, "")

            if current["kind"] == "main":
                # We never got the follow-up. Score on the main alone.
                main_for_scoring = captured or main_transcript
                fu_for_scoring = ""
                fu_question = ""
            else:
                main_for_scoring = main_transcript
                fu_for_scoring = captured
                fu_question = followup_meta.get("question", "")

            try:
                result = score_competency(
                    main_question=comp["question"],
                    main_transcript=main_for_scoring,
                    followup_question=fu_question,
                    followup_transcript=fu_for_scoring,
                    competency_name=comp["competency_name"],
                    followup_goal=comp["followup_goal"],
                )
            except Exception:
                result = {"score": 0, "scripted_flag": False,
                          "rationale": "Interview time expired during this competency."}

            db.save_layer3_result(
                candidate_id=candidate_id,
                competency_order=comp_idx + 1,
                competency_id=comp["competency_id"],
                competency_key=comp["competency_key"],
                competency_name=comp["competency_name"],
                main_question=comp["question"],
                main_transcript=main_for_scoring,
                main_audio_duration_seconds=0.0,
                followup_bucket=followup_meta.get("bucket"),
                followup_question=fu_question,
                followup_transcript=fu_for_scoring,
                followup_audio_duration_seconds=0.0,
                competency_score=result["score"],
                scripted_flag=result["scripted_flag"],
                rationale=result["rationale"],
            )
            already_scored.add(comp["competency_key"])
            st.session_state.l3_answer_scores.append({
                "competency_key": comp["competency_key"],
                "competency_id": comp["competency_id"],
                "score": result["score"],
                "scripted_flag": result["scripted_flag"],
            })

    # Zero-fill every untouched competency.
    for i, comp in enumerate(main_qs):
        if comp["competency_key"] in already_scored:
            continue
        db.save_layer3_result(
            candidate_id=candidate_id,
            competency_order=i + 1,
            competency_id=comp["competency_id"],
            competency_key=comp["competency_key"],
            competency_name=comp["competency_name"],
            main_question=comp["question"],
            main_transcript="",
            main_audio_duration_seconds=0.0,
            followup_bucket=None,
            followup_question=None,
            followup_transcript=None,
            followup_audio_duration_seconds=None,
            competency_score=0,
            scripted_flag=False,
            rationale="Interview time expired before this competency.",
        )
        st.session_state.l3_answer_scores.append({
            "competency_key": comp["competency_key"],
            "competency_id": comp["competency_id"],
            "score": 0,
            "scripted_flag": False,
        })

    st.session_state.l3_finished = True
    st.warning("⏰ Interview time is up. Wrapping up your responses.")
    st.rerun()


# ---------------------------------------------------------------------------
# Pulsating / rotating orb
# ---------------------------------------------------------------------------

def _orb_state(turn_idx: int) -> str:
    """Decide what state the orb should show.

    speaking : right after the AI starts speaking, until the candidate
               appears to be listening (we approximate this).
    listening: while the candidate is recording or about to record.
    idle     : between turns.

    We keep this lightweight: the orb is in 'speaking' for the first ~5
    seconds after a question is rendered with autoplay, then switches to
    'listening' for the rest of the turn. This isn't precise, but it
    looks alive enough without needing browser-side speech-end events.
    """
    # If the autoplay just fired this render, mark the start time.
    spoken_key = f"l3_spoken_{turn_idx}"
    speak_started_key = f"l3_speak_started_{turn_idx}"
    if st.session_state.get(spoken_key) and speak_started_key not in st.session_state:
        st.session_state[speak_started_key] = time.time()

    started = st.session_state.get(speak_started_key)
    if started is None:
        return "idle"
    # Speaking for the first 5s after autoplay; listening afterwards.
    if (time.time() - started) < 5.0:
        return "speaking"
    return "listening"


def _render_orb(state: str) -> None:
    """Render a colored orb (#1DB8F2) below the question header.

    state: "speaking" | "listening" | "idle"
    """
    color = "#1DB8F2"
    uid = uuid.uuid4().hex[:8]

    # Animations are state-driven via a class on the outer wrapper.
    css = f"""
    <style>
      .orb-wrap-{uid} {{
        display: flex;
        justify-content: center;
        align-items: center;
        margin: 8px 0 16px 0;
        height: 140px;
      }}
      .orb-{uid} {{
        width: 100px;
        height: 100px;
        border-radius: 50%;
        background: radial-gradient(circle at 30% 30%, #ffffff 0%, {color} 35%, #0a6f9a 100%);
        position: relative;
      }}
      .orb-{uid}.speaking {{
        animation: orb-pulse-{uid} 1.5s ease-in-out infinite;
        box-shadow: 0 0 30px {color}80, 0 0 60px {color}40;
      }}
      .orb-{uid}.listening {{
        animation: orb-rotate-{uid} 6s linear infinite;
        box-shadow: 0 0 16px {color}60;
      }}
      .orb-{uid}.listening::before {{
        content: "";
        position: absolute;
        top: 12%;
        left: 12%;
        width: 76%;
        height: 76%;
        border-radius: 50%;
        background: radial-gradient(circle at 70% 70%, #ffffff66 0%, transparent 60%);
      }}
      .orb-{uid}.idle {{
        box-shadow: 0 0 8px {color}40;
      }}
      @keyframes orb-pulse-{uid} {{
        0%   {{ transform: scale(1.00); }}
        50%  {{ transform: scale(1.15); }}
        100% {{ transform: scale(1.00); }}
      }}
      @keyframes orb-rotate-{uid} {{
        0%   {{ transform: rotate(0deg); }}
        100% {{ transform: rotate(360deg); }}
      }}
    </style>
    <div class="orb-wrap-{uid}">
      <div class="orb-{uid} {state}"></div>
    </div>
    """
    components.html(css, height=160)

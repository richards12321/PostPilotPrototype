"""Layer 1 view: cognitive assessment.

Theme-level timer (one budget per theme block, not per question). The
candidate sees a continuous countdown over the whole theme. When the
theme runs out, any unanswered questions are auto-marked wrong and the
candidate skips to the next theme intro.

Renders dynamic option counts (3-5 options) and an optional answer-grid
image for abstract reasoning questions.
"""

from __future__ import annotations

import time

import streamlit as st
from streamlit_autorefresh import st_autorefresh

from assessment_logic.layer1_logic import (
    QUESTIONS_PER_THEME,
    THEMES,
    select_questions,
    theme_score,
    theme_time_limit_for,
)
from database import db

from .state import advance_stage


# AI-use flagging thresholds: per-theme score >= 80% AND theme total time
# spent <= 25% of the theme block triggers a "possible AI use" flag.
AI_FLAG_SCORE_THRESHOLD_PCT = 80.0
AI_FLAG_TIME_RATIO = 0.25


# ---------------------------------------------------------------------------
# Hardcoded example questions, one per theme. Shown on the theme intro page
# as "Example question (not graded)" so the candidate knows what to expect.
# These are static and do not go through the seeded random pool.
# ---------------------------------------------------------------------------
EXAMPLE_QUESTIONS = {
    "logical": {
        "stem": (
            "A row of five figures shows: a square pointing up, then the same "
            "square rotated 90° clockwise, then 180°, then 270°, and the "
            "fifth slot is missing. Which option continues the pattern?"
        ),
        "options": [
            "A) The original square pointing up (back to start)",
            "B) A circle of the same size",
            "C) A triangle pointing up",
            "D) The square mirrored",
            "E) A blank slot",
        ],
        "correct": "A",
        "explanation": (
            "The figure rotates 90° clockwise each step. After four 90° turns "
            "(360°) it returns to the starting orientation, so the fifth slot "
            "is the original square pointing up."
        ),
    },
    "numerical": {
        "stem": (
            "Sales were €100,000 in 2022 and €130,000 in 2023. By what "
            "percentage did sales grow from 2022 to 2023?"
        ),
        "options": [
            "A) 13%",
            "B) 23%",
            "C) 30%",
            "D) 33%",
        ],
        "correct": "C",
        "explanation": (
            "Growth = (130,000 - 100,000) / 100,000 = 30,000 / 100,000 = 30%. "
            "Always divide the change by the starting value, not the ending value."
        ),
    },
    "verbal": {
        "stem": (
            "Passage: \"The new bridge opened in March and immediately reduced "
            "morning commute times for drivers heading into the city. Local "
            "businesses near the bridge reported increased foot traffic in the "
            "weeks that followed.\"\n\n"
            "Statement: \"The bridge caused house prices in the area to rise.\""
        ),
        "options": [
            "A) True",
            "B) False",
            "C) Cannot Say",
        ],
        "correct": "C",
        "explanation": (
            "The passage says nothing about house prices. Even if it sounds "
            "plausible that they would rise, you can only judge True or False "
            "based on what the passage actually states. Anything not addressed "
            "is Cannot Say."
        ),
    },
}


def render() -> None:
    candidate_id = st.session_state.candidate_id
    theme_idx = st.session_state.l1_theme_idx
    question_idx = st.session_state.l1_question_idx

    if theme_idx >= len(THEMES):
        _finish_layer(candidate_id)
        return

    # One-time Layer 1 overview, shown before the first theme intro.
    if theme_idx == 0 and not st.session_state.get("l1_overview_seen", False):
        _layer_overview()
        return

    theme = THEMES[theme_idx]

    # Theme intro screen (only before the first question of a theme)
    if question_idx == 0 and not st.session_state.get(f"l1_{theme}_started", False):
        _theme_intro(theme, theme_idx)
        return

    # Lazy-load questions for this theme
    if theme not in st.session_state.l1_questions_cache:
        st.session_state.l1_questions_cache[theme] = select_questions(candidate_id, theme)

    questions = st.session_state.l1_questions_cache[theme]

    if question_idx >= len(questions):
        _finish_theme(candidate_id, theme)
        return

    question = questions[question_idx]
    _render_question(candidate_id, theme, theme_idx, question_idx, question, len(questions))


def _layer_overview() -> None:
    """Layer 1 overview shown once before the first theme intro."""
    st.title("Layer 1: Cognitive Assessment")
    st.markdown(
        f"""
        Layer 1 has three themes you'll work through in order:

        1. **Logical Reasoning**: abstract sequence puzzles. You'll see a row
           of figures with one slot missing, and pick the figure that
           continues the pattern.
        2. **Numerical Reasoning**: short charts and tables, followed by a
           multiple-choice question about the data.
        3. **Verbal Reasoning**: a short passage followed by a statement.
           You decide whether the statement is **True**, **False**, or
           **Cannot Say** based only on the passage.

        Each theme has **{QUESTIONS_PER_THEME} questions** and its own
        **time block, not a per-question timer**. The clock runs continuously
        over the whole theme. When the theme block ends, any unanswered
        questions are marked wrong and you move on to the next theme. You
        cannot revisit questions once answered.

        ### Before you begin, please make sure you have:
        - 📝 **Pen and paper** for working through problems
        - 🧮 **A calculator** (the numerical theme requires arithmetic on
          percentages, ratios, and multi-step figures)
        - 🪑 A quiet, uninterrupted environment for the next ~35 minutes

        Pick the best answer; you will not see whether you got each
        question right.

        - **Don't overthink it.** If you've stared for 30 seconds and nothing
          clicks, pick your best guess and move on. Wrong answers cost the
          same as no answer, and no answer is guaranteed wrong.
        """
    )
    if st.button("Continue to Logical Reasoning", type="primary"):
        st.session_state.l1_overview_seen = True
        st.rerun()


def _render_example(theme: str) -> None:
    """Render a small example question box on the theme intro page."""
    ex = EXAMPLE_QUESTIONS.get(theme)
    if not ex:
        return
    with st.container(border=True):
        st.markdown("**Example question (not graded)**")
        st.markdown(ex["stem"])
        for opt in ex["options"]:
            letter = opt.split(")", 1)[0].strip()
            if letter == ex["correct"]:
                st.markdown(f"- ✅ **{opt}**  *(correct)*")
            else:
                st.markdown(f"- {opt}")
        st.markdown(f"*Why: {ex['explanation']}*")


def _theme_intro(theme: str, theme_idx: int) -> None:
    st.title(f"Layer 1: {theme.capitalize()} Reasoning")
    st.caption(f"Theme {theme_idx + 1} of {len(THEMES)}")

    total_seconds = theme_time_limit_for(theme)
    minutes = total_seconds // 60
    seconds_per_q = total_seconds // QUESTIONS_PER_THEME

    if theme == "logical":
        st.markdown(
            """
            ### Sequence reasoning

            Each question shows a row of figures with one missing slot. The
            figures change from left to right according to a pattern: rotation,
            shape changes, additions, counting, or shading. Work out the
            pattern, then pick the option (A-E) that fits the missing slot.

            ### How the patterns work

            Patterns can involve any combination of:
            - **Shape changes**: squares to triangles, open to filled
            - **Rotation**: figures turning 45° or 90° each step
            - **Addition or subtraction**: elements appearing or
              disappearing across the sequence
            - **Counting**: number of dots, lines, or shapes increasing
              or decreasing
            - **Color or shading**: alternating, inverting, or combining

            ### Tips before you start

            - **Look at the change between adjacent figures first.** The
              step-by-step rule is usually easier to spot than the whole
              pattern at once.
            - **Eliminate impossible options.** Even if you can't see the
              full pattern, you can usually rule out 2-3 options quickly.
            """
        )
    elif theme == "numerical":
        st.markdown(
            """
            ### Numerical reasoning

            Each question shows a **chart or table**, followed by a
            multiple-choice question about the data. You'll need to do
            arithmetic on percentages, ratios, growth rates, and similar.

            Use your calculator. Read the question carefully. The wrong
            answers are usually plausible-looking traps based on misreading
            axes, units, or which row or column to use.
            """
        )
    elif theme == "verbal":
        st.markdown(
            """
            ### Verbal reasoning

            Each question shows a **short passage** followed by a
            **statement**. You'll choose one of three options:

            - **True**: the statement follows logically from the passage.
            - **False**: the statement contradicts the passage.
            - **Cannot Say**: the passage doesn't give you enough
              information to decide either way.

            **Important:** answer based only on what the passage says.
            Don't use outside knowledge, common sense, or assumptions about
            what "should" be true. If the passage doesn't address it
            directly, the answer is almost always **Cannot Say**.
            """
        )

    st.divider()
    _render_example(theme)
    st.divider()

    st.markdown(
        f"You have **{minutes} minutes** total for this theme, across "
        f"{QUESTIONS_PER_THEME} questions. That's roughly "
        f"**{seconds_per_q} seconds per question**. Manage your time. The "
        f"timer runs continuously; it does not reset between questions."
    )

    if st.button(f"Begin {theme.capitalize()} Theme", type="primary"):
        st.session_state[f"l1_{theme}_started"] = True
        # Theme-level clock starts now.
        st.session_state[f"l1_theme_started_at_{theme}"] = time.time()
        # Per-question wall-clock timer also starts here for the first question.
        st.session_state.l1_question_started_at = time.time()
        st.rerun()


def _theme_remaining_seconds(theme: str) -> int:
    """Seconds left in the current theme's time block."""
    started_at = st.session_state.get(f"l1_theme_started_at_{theme}")
    if started_at is None:
        return theme_time_limit_for(theme)
    elapsed = time.time() - started_at
    return max(0, int(theme_time_limit_for(theme) - elapsed))


def _render_question(
    candidate_id: str, theme: str, theme_idx: int, question_idx: int,
    question, total: int,
) -> None:
    theme_total = theme_time_limit_for(theme)

    # Tick every second
    st_autorefresh(interval=1000, key=f"l1_tick_{theme}_{question_idx}")

    # Per-question wall clock (used for DB time_taken_seconds, not surfaced).
    if st.session_state.l1_question_started_at is None:
        st.session_state.l1_question_started_at = time.time()
    q_started_at = st.session_state.l1_question_started_at

    # Theme-level remaining time (the visible timer)
    remaining = _theme_remaining_seconds(theme)

    # Header
    col1, col2 = st.columns([3, 1])
    with col1:
        st.markdown(f"**Layer 1: {theme.capitalize()} Reasoning**")
        st.progress((question_idx) / total, text=f"Question {question_idx + 1} of {total}")
    with col2:
        green_cut = theme_total // 3
        yellow_cut = theme_total // 6
        color = "🟢" if remaining > green_cut else ("🟡" if remaining > yellow_cut else "🔴")
        mins, secs = divmod(remaining, 60)
        st.metric("Theme time left", f"{color} {mins:02d}:{secs:02d}")

    st.divider()

    # If the theme already ran out, auto-mark all remaining questions wrong.
    if remaining <= 0:
        _force_finish_theme_on_timeout(candidate_id, theme, question_idx)
        return

    # Main image (chart, sequence, etc.)
    if question.chart_path:
        try:
            st.image(question.chart_path)
        except Exception:
            pass

    st.markdown(f"### {question.question_text}")

    # Optional second image (abstract: A-E option grid)
    if question.answer_image_path:
        try:
            st.image(question.answer_image_path)
        except Exception:
            pass

    # Options. Dynamic count, support 3/4/5.
    n_opts = len(question.options)
    letters = ["A", "B", "C", "D", "E"][:n_opts]
    selection_key = f"l1_{theme}_{question_idx}_selection"

    # Letter-only rendering is reserved for abstract-reasoning items where
    # the letters are baked into the answer-grid image. Everything else
    # (including verbal True/False/Cannot Say) shows the option text.
    use_letter_only = question.locked and question.answer_image_path is not None

    if use_letter_only:
        display = [f"**{letters[i]}**" for i in range(n_opts)]
    else:
        display = [opt for opt in question.options]

    choice_display = st.radio(
        "Select one:",
        options=display,
        key=selection_key,
        index=None,
        horizontal=use_letter_only,
    )
    chosen_letter = None
    if choice_display is not None:
        chosen_letter = letters[display.index(choice_display)]

    submit_clicked = st.button(
        "Submit answer",
        type="primary",
        disabled=(chosen_letter is None),
        key=f"submit_{theme}_{question_idx}",
    )

    if submit_clicked:
        elapsed_on_q = int(time.time() - q_started_at)
        _save_and_advance(
            candidate_id, theme, theme_idx, question_idx, question,
            chosen_letter, elapsed_on_q, timed_out=False,
        )


def _save_and_advance(
    candidate_id: str, theme: str, theme_idx: int, question_idx: int,
    question, chosen_letter: str | None, elapsed: int, timed_out: bool,
) -> None:
    is_correct = (chosen_letter == question.correct_option)
    db.save_layer1_result(
        candidate_id=candidate_id,
        theme=theme,
        question_id=question.question_id,
        question_text=question.question_text,
        options_shown=question.options,
        correct_option=question.correct_option,
        candidate_answer=chosen_letter,
        is_correct=is_correct,
        time_taken_seconds=max(0, int(elapsed)),
    )

    # Reset per-question wall clock for the next question.
    st.session_state.l1_question_started_at = time.time()
    st.session_state.l1_question_idx = question_idx + 1
    st.rerun()


def _force_finish_theme_on_timeout(
    candidate_id: str, theme: str, current_question_idx: int,
) -> None:
    """Theme timer hit zero. Mark every remaining unanswered question wrong
    (candidate_answer=None, is_correct=0) and advance straight to the next
    theme intro. Skips re-saving questions that already have a row in the DB.
    """
    questions = st.session_state.l1_questions_cache.get(theme, [])

    existing = {
        r["question_id"]
        for r in db.get_layer1_results(candidate_id)
        if r["theme"] == theme
    }

    for idx in range(current_question_idx, len(questions)):
        q = questions[idx]
        if q.question_id in existing:
            continue
        db.save_layer1_result(
            candidate_id=candidate_id,
            theme=theme,
            question_id=q.question_id,
            question_text=q.question_text,
            options_shown=q.options,
            correct_option=q.correct_option,
            candidate_answer=None,
            is_correct=False,
            time_taken_seconds=theme_time_limit_for(theme),
        )

    st.warning(
        f"⏰ Time's up on the {theme.capitalize()} theme. Moving on to the next theme."
    )
    _finish_theme(candidate_id, theme)


def _finish_theme(candidate_id: str, theme: str) -> None:
    rows = [r for r in db.get_layer1_results(candidate_id) if r["theme"] == theme]
    correct = sum(1 for r in rows if r["is_correct"])
    score_pct = theme_score(correct, QUESTIONS_PER_THEME)
    st.session_state.l1_theme_scores[theme] = score_pct

    # AI-use flag: high score plus very fast finish on this theme.
    theme_total_time = sum(int(r.get("time_taken_seconds") or 0) for r in rows)
    flag = (
        score_pct >= AI_FLAG_SCORE_THRESHOLD_PCT
        and theme_total_time <= int(theme_time_limit_for(theme) * AI_FLAG_TIME_RATIO)
    )
    st.session_state[f"l1_ai_flag_{theme}"] = bool(flag)

    st.session_state.l1_theme_idx += 1
    st.session_state.l1_question_idx = 0
    st.session_state.l1_question_started_at = None
    st.rerun()


def _finish_layer(candidate_id: str) -> None:
    """All three themes done. Move on to Layer 2 with no score reveal."""
    st.title("Layer 1 Complete")
    st.success(
        "Nice work, you've finished the cognitive assessment. Your full results "
        "will be shown after you complete all three layers."
    )

    st.markdown(
        """
        ---
        **Next: Layer 2 (Firm Simulation)**

        You'll run a consulting firm for 8 simulated weeks. Assign consultants to
        projects, manage cash and reputation, and respond to events as they
        happen. **20 minutes** in one continuous timer.
        """
    )

    if st.button("Begin Layer 2", type="primary", use_container_width=True):
        advance_stage("layer2")
